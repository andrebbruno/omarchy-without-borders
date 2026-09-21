#!/usr/bin/env python3
"""Omarchy Without Borders — daemon (cliente Linux/Wayland do Mouse Without Borders).

Fase 1: esta máquina é *controlada* por uma máquina Windows com o MWB original.
Fala o protocolo nativo (porta base+1, AES-CBC/PBKDF2, pacotes de 32/64 B), então
o lado Windows não precisa de nada além do PowerToys, com a mesma chave de segurança
e o nome desta máquina no Matrix.

Uso: owb run [--config ~/.config/owb/config.json] [-v]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import random
import socket
import struct
import sys
import threading
import time

from . import proto as P
from .i18n import set_language, t
from .vk_map import vk_to_keycode

log = logging.getLogger("owb")
SOCK_PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "owb.sock")

DEFAULT_CONFIG = {
    "key": "",                    # chave de segurança do MWB (16+ chars, igual à do Windows)
    "machine_name": "",           # vazio = hostname em maiúsculas
    "machine_id": 0,              # 0 = gerar e salvar
    "port": 15100,                # porta base do MWB (mensagens usam port+1)
    "peers": [],                  # IPs/hosts das máquinas Windows (conectamos a elas)
    "listen": True,               # aceitar conexões iniciadas pelo Windows em port+1
    "heartbeat_seconds": 30,
    "keyboard_layout": "us",
    "keyboard_variant": "",
    "language": "auto",           # "auto" (LANG) | "en" | "pt-BR"
    "crypto": "legacy",           # "legacy" = PowerToys lançado (<= 0.100.x); "salted" = branch main
    "vk_overrides": {},           # {"0xBA": 39} para ajustar tecla a tecla
}


class Config:
    def __init__(self, path: str):
        self.path = os.path.expanduser(path)
        data = dict(DEFAULT_CONFIG)
        if os.path.exists(self.path):
            with open(self.path, encoding="utf-8") as f:
                data.update(json.load(f))
        changed = False
        if not data["machine_name"]:
            data["machine_name"] = socket.gethostname().split(".")[0].upper()[:32]
            changed = True
        if not data["machine_id"]:
            data["machine_id"] = random.randint(1, 0x7FFFFFFE)
            changed = True
        self.data = data
        if changed:
            self.save()

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)
        os.chmod(self.path, 0o600)

    def __getattr__(self, k):
        try:
            return self.data[k]
        except KeyError:
            raise AttributeError(k)


class Peer:
    """Uma conexão TCP com uma máquina remota (cliente ou aceita), com handshake MWB."""

    def __init__(self, daemon: "Daemon", sock: socket.socket, is_client: bool, label: str):
        self.d = daemon
        self.sock = sock
        self.is_client = is_client
        self.label = label
        self.remote_name = label
        self.remote_id = P.ID_NONE
        self.trusted = False
        self.alive = True
        self.legacy = daemon.cfg.crypto != "salted"
        self.enc = P.Encryptor(daemon.key, legacy=self.legacy)
        self.dec: P.Decryptor | None = None
        self.send_lock = threading.Lock()
        self.my_challenge: tuple[int, ...] = ()
        self.clip_buf: bytearray | None = None
        self.clip_image = False
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

    # ---------------------------------------------------------- envio
    def _send_raw(self, data: bytes):
        with self.send_lock:
            self.sock.sendall(data)

    def send(self, pkg: P.Package):
        if pkg.src == P.ID_NONE:
            pkg.src = self.d.machine_id
        buf = bytearray(pkg.wire())
        P.seal(buf, self.d.magic)
        self._send_raw(self.enc.encrypt(bytes(buf)))

    def send_typed(self, ptype: int, des: int = P.ID_ALL) -> None:
        pkg = P.Package()
        pkg.type = ptype
        pkg.des = des
        pkg.id = self.d.next_id()
        pkg.machine_name = self.d.machine_name
        self.send(pkg)

    # ---------------------------------------------------------- recepção
    def _recv_exact(self, n: int) -> bytes:
        out = bytearray()
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("socket fechado pelo remoto")
            out += chunk
        return bytes(out)

    def _recv_plain(self, n: int) -> bytes:
        return self.dec.decrypt(self._recv_exact(n))

    def run(self):
        try:
            # 1) nosso lado de escrita: header em claro + bloco aleatório cifrado
            if not self.legacy:
                self._send_raw(self.enc.header())
            self._send_raw(self.enc.initial_block())
            # 2) 10x Handshake com desafio aleatório (MainTCPRoutine)
            hs = P.Package(os.urandom(P.PACKAGE_SIZE_EX))
            hs.type = P.PackageType.Handshake
            hs.machine_name = self.d.machine_name
            for _ in range(10):
                self.send(hs)
            hs.invert_machines()
            self.my_challenge = hs.machines()
            # 3) lado de leitura: header do remoto + bloco aleatório
            header = b"" if self.legacy else self._recv_exact(P.Decryptor.HEADER_LEN)
            self.dec = P.Decryptor(self.d.key, header, legacy=self.legacy)
            self._recv_plain(P.BLOCK)
            log.info("[%s] handshake enviado, aguardando ack", self.label)
            bad = 0
            while self.alive:
                buf = bytearray(self._recv_plain(P.PACKAGE_SIZE))
                if not P.unseal(buf, self.d.magic):
                    bad += 1
                    log.warning("[%s] pacote inválido (%d) — chave diferente?", self.label, bad)
                    if bad > 5:
                        raise ConnectionError("muitos pacotes inválidos; verifique a chave")
                    continue
                pkg = P.Package(buf)
                if pkg.is_big:
                    pkg.buf[P.PACKAGE_SIZE:] = self._recv_plain(P.PACKAGE_SIZE)
                self._handle(pkg)
        except (ConnectionError, OSError) as e:
            log.info("[%s] desconectado: %s", self.label, e)
        except Exception:
            log.exception("[%s] erro", self.label)
        finally:
            self.alive = False
            try:
                self.sock.close()
            except OSError:
                pass
            self.d.peer_gone(self)

    def _handle(self, pkg: P.Package):
        pt = pkg.type
        if pt == P.PackageType.Handshake:
            ack = P.Package(pkg.buf)
            ack.type = P.PackageType.HandshakeAck
            ack.src = P.ID_NONE
            ack.machine_name = self.d.machine_name
            ack.invert_machines()
            self.send(ack)
            return
        if pt == P.PackageType.HandshakeAck:
            if self.trusted:
                return
            if pkg.machines() == self.my_challenge:
                self.trusted = True
                self.remote_id = pkg.src
                self.remote_name = pkg.machine_name or self.label
                log.info("[%s] CONFIÁVEL: %s (id=%d)", self.label, self.remote_name, self.remote_id)
                if not self.d.peer_by_name(self.remote_name):
                    self.d.notify(t("d.connected", name=self.remote_name), self.label, "low")
                self.d.learn(self.remote_name, self.remote_id)
                self.send_typed(P.PackageType.Heartbeat)
            else:
                log.error("[%s] ack inválido — chave de segurança diferente", self.label)
                self.d.notify(t("d.badkey"), t("d.badkey_body", addr=self.label), "critical")
                raise ConnectionError("ack inválido")
            return
        if not self.trusted:
            return
        if pt in (P.PackageType.Heartbeat, P.PackageType.Heartbeat_ex, P.PackageType.Awake, P.PackageType.Hello):
            self.d.learn(pkg.machine_name, pkg.src)
            if pt == P.PackageType.Hello:
                self.send_typed(P.PackageType.Heartbeat)
            return
        if pt in (P.PackageType.Heartbeat_ex_l2,):
            self.send_typed(P.PackageType.Heartbeat_ex_l3)
            return
        if pt == P.PackageType.ByeBye:
            log.info("[%s] ByeBye de %s", self.label, self.remote_name)
            self.d.events.put(("hide", None))
            return
        if (pt & P.PackageType.Matrix) == P.PackageType.Matrix:
            i = pkg.src
            if 1 <= i <= 4:
                self.d.matrix[i - 1] = pkg.machine_name
                if i == 4:
                    # flags travel with the 4th slot, like MWB's UpdateMachineMatrix
                    two_rows = bool(pt & P.PackageType.MatrixTwoRowFlag)
                    circle = bool(pt & P.PackageType.MatrixSwapFlag)
                    changed = (self.d.matrix != self.d.last_matrix or two_rows != self.d.matrix_two_rows
                               or circle != self.d.matrix_circle)
                    self.d.matrix_two_rows, self.d.matrix_circle = two_rows, circle
                    if changed:
                        self.d.last_matrix = list(self.d.matrix)
                        log.info("matrix from %s: %s (rows=%d, wrap=%s)", self.remote_name, self.d.matrix,
                                 2 if two_rows else 1, circle)
                        self.d.cfg.data.update({"matrix": list(self.d.matrix), "matrix_two_rows": two_rows,
                                                "matrix_circle": circle})
                        self.d.cfg.save()
            return
        if pt == P.PackageType.Mouse:
            if pkg.des in (self.d.machine_id, P.ID_ALL):
                self.d.events.put(("mouse", pkg))
                self.d.wake()
            return
        if pt == P.PackageType.Keyboard:
            if pkg.des in (self.d.machine_id, P.ID_ALL):
                self.d.events.put(("key", pkg))
                self.d.wake()
            return
        if pt == P.PackageType.HideMouse:
            self.d.events.put(("hide", None))
            self.d.wake()
            return
        if pt in (P.PackageType.ClipboardText, P.PackageType.ClipboardImage):
            if self.clip_buf is None:
                self.clip_buf = bytearray()
                self.clip_image = pt == P.PackageType.ClipboardImage
            self.clip_buf += pkg.buf[16:64]
            if len(self.clip_buf) > 4 * 1024 * 1024:
                log.warning("[%s] clipboard recebido grande demais; descartando", self.label)
                self.clip_buf = None
            return
        if pt == P.PackageType.ClipboardDataEnd:
            if self.clip_buf is not None:
                data, image = bytes(self.clip_buf), self.clip_image
                self.clip_buf = None
                self.d.clipboard_received(self.remote_name, data, image)
            return
        if pt == P.PackageType.Clipboard:
            log.info("[%s] %s tem clipboard grande (>1 MB) — não suportado ainda", self.label, self.remote_name)
            return
        if pt in (P.PackageType.ClipboardCapture, P.PackageType.ClipboardAsk,
                 P.PackageType.MachineSwitched, P.PackageType.NextMachine, P.PackageType.Hi):
            log.debug("[%s] pacote %s ignorado (fase 1)", self.label, P.PackageType(pt).name)
            return
        log.debug("[%s] tipo desconhecido %d", self.label, pt)


class Daemon:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.key = cfg.key
        self.magic = P.magic_number(self.key)
        self.machine_name = cfg.machine_name
        self.machine_id = cfg.machine_id
        self.events: queue.Queue = queue.Queue()
        self.peers: list[Peer] = []
        self.peers_lock = threading.Lock()
        self.known: dict[str, int] = {}
        self.matrix = list(cfg.data.get("matrix") or ["", "", "", ""])
        self.last_matrix: list[str] = list(self.matrix)
        self.matrix_two_rows = bool(cfg.data.get("matrix_two_rows", False))
        self.matrix_circle = bool(cfg.data.get("matrix_circle", False))
        self._pkg_id = random.randint(1, 1 << 30)
        self.started = time.monotonic()
        self._id_lock = threading.Lock()
        self.vk_overrides = {int(k, 0): int(v) for k, v in cfg.vk_overrides.items()}
        log.info("máquina %s id=%d magic=0x%08X porta=%d", self.machine_name, self.machine_id, self.magic, cfg.port + 1)

    def next_id(self) -> int:
        with self._id_lock:
            self._pkg_id = (self._pkg_id + 1) & 0x7FFFFFFF
            return self._pkg_id

    def notify(self, title: str, body: str = "", urgency: str = "normal"):
        if not self.cfg.data.get("notifications", True):
            return
        try:
            import subprocess
            subprocess.Popen(["notify-send", "-a", t("d.appname"), "-u", urgency, title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass

    def wake(self):
        w = getattr(self, "_wake", None)
        if w is not None:
            try:
                os.write(w, b"x")
            except OSError:
                pass

    def learn(self, name: str, mid: int):
        if name and mid and self.known.get(name) != mid:
            self.known[name] = mid
            log.info("máquina conhecida: %s -> %d", name, mid)

    # ---------------------------------------------------------- conexões
    def add_peer(self, sock: socket.socket, is_client: bool, label: str):
        p = Peer(self, sock, is_client, label)
        with self.peers_lock:
            self.peers.append(p)
        threading.Thread(target=p.run, name=f"peer-{label}", daemon=True).start()

    def close_peers_with_reset(self):
        """Close every peer socket with an RST instead of a FIN.

        MWB only re-dials a machine on its own after a WSAECONNRESET (one retry, ~30 s of
        attempts); a graceful close is just "read returned 0" and, unless the matrix changed,
        it never reconnects until the user presses Ctrl+Alt+R. This matters for machines that
        can only connect outbound (corporate firewall) — we cannot dial them back.
        """
        with self.peers_lock:
            peers = list(self.peers)
        for p in peers:
            try:
                p.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
                p.sock.close()
            except OSError:
                pass

    def peer_gone(self, p: Peer):
        with self.peers_lock:
            if p in self.peers:
                self.peers.remove(p)

    def has_client_to(self, host: str) -> bool:
        with self.peers_lock:
            return any(p.is_client and p.label == host and p.alive for p in self.peers)

    def connector_loop(self):
        while True:
            for host in self.cfg.peers:
                if self.has_client_to(host):
                    continue
                try:
                    s = socket.create_connection((host, self.cfg.port + 1), timeout=5)
                    s.settimeout(None)
                    log.info("conectado a %s:%d", host, self.cfg.port + 1)
                    self.add_peer(s, True, host)
                except OSError as e:
                    log.debug("conexão a %s falhou: %s", host, e)
            time.sleep(5)

    def listener_loop(self):
        # dual-stack: o Windows resolve nosso nome por LLMNR e tenta IPv6 antes do IPv4
        srv = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        srv.bind(("::", self.cfg.port + 1))
        srv.listen(8)
        log.info("ouvindo em [::]:%d (IPv4+IPv6)", self.cfg.port + 1)
        while True:
            s, addr = srv.accept()
            ip = addr[0].replace("::ffff:", "")
            log.info("conexão recebida de %s", ip)
            self.add_peer(s, False, ip)

    # ---------------------------------------------------------- controle (fase 2, sintético)
    def peer_by_name(self, name: str):
        """Conexão confiável mais recente com a máquina (o MWB abre várias; a mais nova é a viva)."""
        with self.peers_lock:
            cands = [p for p in self.peers if p.trusted and p.alive and p.remote_name.upper() == name.upper()]
        return cands[-1] if cands else None

    def _send_safe(self, peer, fn, *a):
        """Envia; se a conexão estiver morta, marca-a e tenta outra da mesma máquina. Retorna o peer usado."""
        try:
            fn(peer, *a)
            return peer
        except OSError as e:
            log.info("conexão com %s morta (%s); trocando", peer.remote_name, e)
            peer.alive = False
            self.peer_gone(peer)
            alt = self.peer_by_name(peer.remote_name)
            if alt is None:
                raise
            fn(alt, *a)
            return alt

    def send_mouse(self, peer: "Peer", x: int, y: int, flags: int = P.WM_MOUSEMOVE, wheel: int = 0):
        pkg = P.Package()
        pkg.type = P.PackageType.Mouse
        pkg.des = peer.remote_id
        pkg.id = self.next_id()
        pkg.mx, pkg.my, pkg.wheel, pkg.mflags = x, y, wheel, flags
        peer.send(pkg)

    def send_key(self, peer: "Peer", vk: int, down: bool, extended: bool = False):
        pkg = P.Package()
        pkg.type = P.PackageType.Keyboard
        pkg.des = peer.remote_id
        pkg.id = self.next_id()
        pkg.vk = vk
        pkg.kflags = (0 if down else P.LLKHF_UP) | (P.LLKHF_EXTENDED if extended else 0)
        peer.send(pkg)

    def tap_key(self, peer: "Peer", vk: int, extended: bool = False, hold: float = 0.03):
        self.send_key(peer, vk, True, extended)
        time.sleep(hold)
        self.send_key(peer, vk, False, extended)
        time.sleep(0.04)

    def type_text(self, peer: "Peer", text: str):
        """Texto ASCII simples: letras/dígitos/espaço via VK (letras = VK maiúsculo, sem shift)."""
        for ch in text:
            if ch == " ":
                self.tap_key(peer, 0x20)
            elif ch.isalpha() and ch.isascii():
                self.tap_key(peer, ord(ch.upper()))
            elif ch.isdigit():
                self.tap_key(peer, ord(ch))
            elif ch == "\n":
                self.tap_key(peer, 0x0D)

    def control_loop(self, path: str = SOCK_PATH):
        """Comandos de teste por socket UNIX: 'circle NOME [seg]' | 'move NOME X Y' (0..65535)."""
        import math
        if os.path.exists(path):
            os.unlink(path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(2)
        while True:
            c, _ = srv.accept()
            try:
                line = c.makefile().readline().strip().split()
                if not line:
                    continue
                if line[0] == "clipchange":
                    self.clipboard_changed()
                    continue
                if line[0] == "status":
                    c.sendall(json.dumps(self.status(), ensure_ascii=False).encode() + b"\n")
                    continue
                if line[0] == "release":
                    self._host_return()
                    c.sendall(b"ok\n")
                    continue
                cmd, name = line[0], line[1]
                peer = self.peer_by_name(name)
                if not peer:
                    c.sendall(f"máquina {name} não conectada; conhecidas: {self.known}\n".encode())
                    continue
                if cmd == "move":
                    self.send_mouse(peer, int(line[2]), int(line[3]))
                    c.sendall(b"ok\n")
                elif cmd == "run":
                    # 'run NOME programa [mensagem...]' -> Win, digita programa, Enter, digita mensagem
                    prog, msg = line[2], " ".join(line[3:])
                    self.tap_key(peer, 0x5B, extended=True, hold=0.08)
                    time.sleep(1.2)
                    self.type_text(peer, prog)
                    time.sleep(0.4)
                    self.tap_key(peer, 0x0D)
                    if msg:
                        time.sleep(3.0)
                        self.type_text(peer, msg + "\n")
                    c.sendall(f"ok: {prog} em {peer.remote_name}\n".encode())
                elif cmd == "circle":
                    secs = float(line[2]) if len(line) > 2 else 4.0
                    n = int(secs * 60)
                    for i in range(n):
                        a = 2 * math.pi * i / 120
                        self.send_mouse(peer, int(32767 + 12000 * math.cos(a)), int(32767 + 12000 * math.sin(a)))
                        time.sleep(1 / 60)
                    c.sendall(f"ok: {n} pacotes para {peer.remote_name}\n".encode())
            except Exception as e:  # noqa: BLE001
                log.warning("controle: %s", e)
            finally:
                c.close()

    def heartbeat_loop(self):
        while True:
            time.sleep(self.cfg.heartbeat_seconds)
            with self.peers_lock:
                peers = [p for p in self.peers if p.trusted and p.alive]
            for p in peers:
                try:
                    p.send_typed(P.PackageType.Heartbeat)
                except OSError:
                    pass

    # ---------------------------------------------------------- loop principal (injeção + captura)
    def _handle_incoming(self, inj, kind, pkg, buttons, stats):
        """Pacotes vindos de um host Windows que nos controla (fase 1)."""
        from .wl_inject import BTN_EXTRA, BTN_SIDE
        if kind == "mouse":
            stats["mouse"] += 1
            f = pkg.mflags
            if f == P.WM_MOUSEMOVE:
                inj.move_abs(pkg.mx, pkg.my)
            elif f in buttons:
                inj.move_abs(pkg.mx, pkg.my)
                inj.button(*buttons[f])
            elif f in (P.WM_XBUTTONDOWN, P.WM_XBUTTONUP):
                inj.button(BTN_EXTRA if pkg.wheel == 2 else BTN_SIDE, f == P.WM_XBUTTONDOWN)
            elif f == P.WM_MOUSEWHEEL:
                inj.wheel(_signed16(pkg.wheel), False)
            elif f == P.WM_MOUSEHWHEEL:
                inj.wheel(_signed16(pkg.wheel), True)
        elif kind == "key":
            stats["key"] += 1
            ext = bool(pkg.kflags & P.LLKHF_EXTENDED)
            up = bool(pkg.kflags & P.LLKHF_UP)
            kc = self.vk_overrides.get(pkg.vk) or vk_to_keycode(pkg.vk, ext)
            if kc is None:
                log.warning("VK 0x%02X sem mapeamento (ext=%s)", pkg.vk, ext)
            else:
                inj.key(kc, not up)
        elif kind == "hide":
            inj.release_all()

    def status(self) -> dict:
        with self.peers_lock:
            peers = [{"name": p.remote_name, "id": p.remote_id, "addr": p.label, "client": p.is_client,
                      "trusted": p.trusted} for p in self.peers if p.alive]
        nb = self.neighbours()
        cap = getattr(self, "_cap", None)
        host = getattr(self, "host", None)
        return {
            "machine_name": self.machine_name,
            "machine_id": self.machine_id,
            "port": self.cfg.port + 1,
            "crypto": self.cfg.data.get("crypto", "legacy"),
            "uptime_s": int(time.monotonic() - self.started),
            "peers": peers,
            "known": self.known,
            "matrix": self.matrix,
            "matrix_two_rows": self.matrix_two_rows,
            "matrix_circle": self.matrix_circle,
            "neighbours": nb,
            "edges": sorted(cap.edges) if cap else [],
            "capture": bool(cap and cap.enabled),
            "controlling": host["peer"].remote_name if host else None,
            "clipboard": bool(self.cfg.data.get("share_clipboard", True)),
            "keyboard_layout": self.cfg.keyboard_layout,
        }

    # -- clipboard --------------------------------------------------------------------
    def clipboard_received(self, from_name: str, data: bytes, image: bool):
        from . import clipboard as C
        # a mesma máquina costuma ter 2 conexões conosco: ignorar cópia idêntica recente
        key = ("image" if image else "text", data)
        if getattr(self, "clip_last", None) == key and time.monotonic() < getattr(self, "clip_suppress_until", 0) + 3:
            return
        try:
            if image:
                png = data.rstrip(bytes([0]))  # padding do ultimo chunk; decodificadores PNG toleram
                C.set_image_png(png)
                log.info("clipboard <- %s: imagem PNG (%d B)", from_name, len(data))
            else:
                parts = C.decode_text(data)
                txt = parts.get("TXT")
                if txt is None:
                    log.info("clipboard <- %s: sem TXT (%s)", from_name, list(parts))
                    return
                C.set_text(txt)
                log.info("clipboard <- %s: %d chars", from_name, len(txt))
            self.clip_last = ("image" if image else "text", data)
            self.clip_suppress_until = time.monotonic() + 1.5
        except Exception as e:  # noqa: BLE001
            log.warning("clipboard recebido inválido de %s: %s", from_name, e)

    def clipboard_changed(self):
        """Chamado pelo wl-paste --watch: lê o clipboard local e manda para todas as máquinas."""
        from . import clipboard as C
        if time.monotonic() < getattr(self, "clip_suppress_until", 0):
            return
        types = C.get_types()
        if any(mt.startswith("text/") for mt in types):
            txt = C.get_text()
            if not txt:
                return
            data, image = C.encode_text(txt), False
            desc = f"{len(txt)} chars"
        elif "image/png" in types:
            png = C.get_image_png()
            if not png:
                return
            data, image = png, True
            desc = f"imagem PNG {len(png)} B"
        else:
            return
        if getattr(self, "clip_last", None) == (("image" if image else "text"), data):
            return
        if len(data) > C.MAX_INLINE:
            log.info("clipboard local > 1 MB — não enviado (limite do modo inline)")
            return
        self.clip_last = ("image" if image else "text", data)
        # uma conexão por máquina (ClipboardText não é deduplicado pelo Id no MWB)
        with self.peers_lock:
            by_name = {}
            for p in self.peers:
                if p.trusted and p.alive:
                    by_name[p.remote_name.upper()] = p
        sent = 0
        for p in by_name.values():
            try:
                for piece in C.chunks(data):
                    pkg = P.Package()
                    pkg.type = P.PackageType.ClipboardImage if image else P.PackageType.ClipboardText
                    pkg.des = P.ID_ALL
                    pkg.id = self.next_id()
                    pkg.buf[16:64] = piece
                    p.send(pkg)
                end = P.Package()
                end.type = P.PackageType.ClipboardDataEnd
                end.des = P.ID_ALL
                end.id = self.next_id()
                p.send(end)
                sent += 1
            except OSError as e:
                log.info("clipboard -> %s falhou: %s", p.remote_name, e)
        log.info("clipboard -> %d máquina(s): %s", sent, desc)

    def clipboard_watch_loop(self):
        """Mantém um wl-paste --watch que avisa o daemon a cada mudança (via socket de controle)."""
        import subprocess
        from . import clipboard as C
        script = os.path.expanduser("~/.config/owb/clipwatch.sh")
        os.makedirs(os.path.dirname(script), exist_ok=True)
        with open(script, "w") as f:
            f.write(C.WATCH_SCRIPT)
        os.chmod(script, 0o755)
        while True:
            try:
                proc = subprocess.Popen(["wl-paste", "--watch", script], env=C._env(),
                                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                log.info("wl-paste --watch iniciado (pid %d)", proc.pid)
                proc.wait()
                log.warning("wl-paste --watch terminou (rc=%s); reiniciando em 5 s", proc.returncode)
            except FileNotFoundError:
                log.error("wl-paste não encontrado — clipboard desativado")
                return
            time.sleep(5)

    # -- lado host (fase 2): vizinhos pelo matrix ------------------------------------
    def neighbours(self) -> dict[str, str]:
        """{'left'|'right'|'top'|'bottom': name} following MWB's MoveLeft/Right/Up/Down.

        One row: next non-empty *connected* slot in that direction (disconnected machines are
        skipped, like MWB's LiveMachineMatrix); wrap around when the matrix is circular.
        Two rows: grid [[0, 1], [2, 3]], no skipping; circular = opposite cell of the same row/column.
        """
        me = self.machine_name.upper()
        mc = [n or "" for n in self.matrix] + [""] * (4 - len(self.matrix))
        connected = lambda n: bool(n) and self.peer_by_name(n) is not None  # noqa: E731
        out: dict[str, str] = {}
        if not self.matrix_two_rows:
            names = [n for n in mc if n]
            idx = next((i for i, n in enumerate(names) if n.upper() == me), -1)
            if idx < 0:
                return out
            order_r = names[idx + 1:] + (names[:idx] if self.matrix_circle else [])
            order_l = names[:idx][::-1] + (names[idx + 1:][::-1] if self.matrix_circle else [])
            for edge, order in (("right", order_r), ("left", order_l)):
                n = next((n for n in order if connected(n)), "")
                if n:
                    out[edge] = n
            return out
        idx = next((i for i, n in enumerate(mc) if n.upper() == me), -1)
        if idx < 0:
            return out
        row, col = divmod(idx, 2)
        cand = {"right": (row, 1), "left": (row, 0), "bottom": (1, col), "top": (0, col)}
        for edge, (r, c) in cand.items():
            j = r * 2 + c
            if j == idx:
                if not self.matrix_circle:
                    continue
                # wrap: the opposite cell in the same row/column (MWB's MatrixCircle for two rows)
                j = (r * 2 + (1 - c)) if edge in ("left", "right") else ((1 - r) * 2 + c)
            if mc[j] and mc[j].upper() != me:
                out[edge] = mc[j]
        return out

    def refresh_edges(self, cap):
        nb = self.neighbours()
        edges = {e for e, n in nb.items() if self.peer_by_name(n)}
        if edges != cap.edges or not cap.enabled:
            try:
                cap.set_edges(edges)
            except Exception as e:  # noqa: BLE001
                log.warning("barreiras: %s", e)

    def _host_activate(self, aid, x, y, edge):
        nb = self.neighbours()
        target = self.peer_by_name(nb.get(edge, ""))
        if not target:
            log.warning("borda %s ativada sem vizinho conectado — liberando", edge)
            _, _, w, h = self._cap.geom
            # devolver o cursor 2 px para dentro da tela, na mesma altura (evita reativar a barreira)
            back = {"left": (2.0, y), "right": (w - 2.0, y), "top": (x, 2.0), "bottom": (x, h - 2.0)}[edge]
            self._cap.release(aid, *back)
            return
        _, _, w, h = self._cap.geom
        # the cursor enters the remote screen on the opposite edge, at the same height/column
        vx = {"right": 0.0, "left": float(w)}.get(edge, max(0.0, min(float(w), x)))
        vy = {"bottom": 0.0, "top": float(h)}.get(edge, max(0.0, min(float(h), y)))
        self.host = {"aid": aid, "peer": target, "edge": edge, "w": w, "h": h, "vx": vx, "vy": vy,
                     "scroll_acc": 0.0}
        try:
            target = self._send_safe(target, lambda p: p.send_typed(P.PackageType.MachineSwitched, p.remote_id))
            self.host["peer"] = target
            self._send_safe(target, lambda p: self.send_mouse(p, int(self.host["vx"] * 65535 / w), int(self.host["vy"] * 65535 / h)))
        except OSError as e:
            log.warning("falha ao iniciar controle de %s: %s", target.remote_name, e)
        log.info("controlando %s (borda %s, x=%.0f, y=%.0f)", target.remote_name, edge, x, y)
        self.notify(t("d.controlling", name=target.remote_name), t("d.controlling_body"), "low")

    def _host_return(self):
        h = self.host
        if not h:
            return
        try:
            self._send_safe(h["peer"], lambda p: p.send_typed(P.PackageType.HideMouse, p.remote_id))
        except OSError:
            pass
        # re-enter 2 px inside our screen on the edge we left through
        x, y = {"left": (2.0, h["vy"]), "right": (h["w"] - 2.0, h["vy"]),
                "top": (h["vx"], 2.0), "bottom": (h["vx"], h["h"] - 2.0)}[h["edge"]]
        self._cap.release(h["aid"], x, y)
        log.info("voltando para o Omarchy (x=%.0f, y=%.0f)", x, y)
        self.host = None

    def _host_deactivated(self, aid):
        if self.host and self.host["aid"] == aid:
            log.info("captura encerrada pelo compositor")
            self.host = None

    def _host_events(self, events):
        """Eventos EIS enquanto controlamos uma máquina remota."""
        from .ei_receiver import Button, Key, Motion, Scroll
        from .vk_map import keycode_to_vk
        from .wl_inject import BTN_EXTRA, BTN_LEFT, BTN_MIDDLE, BTN_RIGHT, BTN_SIDE
        h = self.host
        if not h:
            return
        peer, w, hgt = h["peer"], h["w"], h["h"]
        btn_map = {BTN_LEFT: (P.WM_LBUTTONDOWN, P.WM_LBUTTONUP), BTN_RIGHT: (P.WM_RBUTTONDOWN, P.WM_RBUTTONUP),
                   BTN_MIDDLE: (P.WM_MBUTTONDOWN, P.WM_MBUTTONUP), BTN_SIDE: (P.WM_XBUTTONDOWN, P.WM_XBUTTONUP),
                   BTN_EXTRA: (P.WM_XBUTTONDOWN, P.WM_XBUTTONUP)}
        moved = False
        try:
            for ev in events:
                if isinstance(ev, Motion):
                    h["vx"] += ev.dx
                    h["vy"] += ev.dy
                    # crossed back over the edge we came through?
                    e = h["edge"]
                    if ((e == "right" and h["vx"] < 0) or (e == "left" and h["vx"] > w)
                            or (e == "bottom" and h["vy"] < 0) or (e == "top" and h["vy"] > hgt)):
                        self._host_return()
                        return
                    h["vx"] = max(0.0, min(float(w), h["vx"]))
                    h["vy"] = max(0.0, min(float(hgt), h["vy"]))
                    moved = True
                elif isinstance(ev, Button):
                    if moved:
                        self.send_mouse(peer, int(h["vx"] * 65535 / w), int(h["vy"] * 65535 / hgt))
                        moved = False
                    if ev.button in btn_map:
                        down, up = btn_map[ev.button]
                        wheel = 2 if ev.button == BTN_EXTRA else (1 if ev.button == BTN_SIDE else 0)
                        self.send_mouse(peer, int(h["vx"] * 65535 / w), int(h["vy"] * 65535 / hgt),
                                        down if ev.pressed else up, wheel)
                elif isinstance(ev, Scroll):
                    if ev.discrete:
                        vy, vx = -int(ev.dy), int(ev.dx)
                    else:
                        h["scroll_acc"] += ev.dy
                        vy, vx = 0, 0
                        if abs(h["scroll_acc"]) >= 15:
                            vy = -120 * int(h["scroll_acc"] / 15)
                            h["scroll_acc"] -= 15 * int(h["scroll_acc"] / 15)
                    if vy:
                        self.send_mouse(peer, int(h["vx"] * 65535 / w), int(h["vy"] * 65535 / hgt), P.WM_MOUSEWHEEL, vy)
                    if vx:
                        self.send_mouse(peer, int(h["vx"] * 65535 / w), int(h["vy"] * 65535 / hgt), P.WM_MOUSEHWHEEL, vx)
                elif isinstance(ev, Key):
                    m = keycode_to_vk(ev.key)
                    if m is None:
                        log.warning("keycode %d sem VK", ev.key)
                    else:
                        self.send_key(peer, m[0], ev.pressed, m[1])
            if moved:
                self.send_mouse(peer, int(h["vx"] * 65535 / w), int(h["vy"] * 65535 / hgt))
        except OSError as e:
            peer.alive = False
            self.peer_gone(peer)
            alt = self.peer_by_name(peer.remote_name)
            if alt is not None:
                log.info("conexão com %s caiu (%s); continuando por outra", peer.remote_name, e)
                h["peer"] = alt
            else:
                log.warning("conexão com %s caiu durante o controle: %s", peer.remote_name, e)
                self._host_return()

    def main_loop(self):
        import select
        from .capture import InputCapture
        from .ei_receiver import EiReceiver
        from .wl_inject import BTN_LEFT, BTN_MIDDLE, BTN_RIGHT, WaylandInjector
        inj = WaylandInjector(layout=self.cfg.keyboard_layout, variant=self.cfg.keyboard_variant)
        log.info("injetor Wayland pronto (layout %s)", self.cfg.keyboard_layout)
        self.host = None
        self._cap = None
        self._ei = None
        if inj.capture_mgr is not None and self.cfg.data.get("host_mode", True):
            def on_fd(fd):
                self._ei = EiReceiver(fd)
                log.info("socket EIS recebido (fd=%d)", fd)
            self._cap = InputCapture(inj.capture_mgr, on_fd, self._host_activate, self._host_deactivated)
            inj.flush()
        else:
            log.info("modo host indisponível (sem hyprland_input_capture_manager_v1)")
        buttons = {
            P.WM_LBUTTONDOWN: (BTN_LEFT, True), P.WM_LBUTTONUP: (BTN_LEFT, False),
            P.WM_RBUTTONDOWN: (BTN_RIGHT, True), P.WM_RBUTTONUP: (BTN_RIGHT, False),
            P.WM_MBUTTONDOWN: (BTN_MIDDLE, True), P.WM_MBUTTONUP: (BTN_MIDDLE, False),
        }
        stats = {"mouse": 0, "key": 0}
        last_log = last_edges = time.monotonic()
        rpipe, wpipe = os.pipe()
        self._wake = wpipe

        # encerramento limpo: devolver o cursor, soltar teclas e sair sem rodar os destrutores
        # do pywayland (que podem segfaultar na finalização do interpretador → "Process crashed")
        import signal

        def _shutdown(signum, _frame):
            log.info("encerrando (sinal %d)", signum)
            try:
                if self.host:
                    self._host_return()
                inj.release_all()
                inj.flush()
            except Exception:  # noqa: BLE001
                pass
            self.close_peers_with_reset()
            os._exit(0)

        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)
        while True:
            fds = [inj.fileno(), rpipe]
            if self._ei is not None:
                fds.append(self._ei.fileno())
            inj.flush()
            readable, _, _ = select.select(fds, [], [], 0.5)
            if inj.fileno() in readable:
                inj.dispatch_pending()
            if self._ei is not None and self._ei.fileno() in readable:
                evs = self._ei.pump()
                if evs and self.host:
                    self._host_events(evs)
            if rpipe in readable:
                os.read(rpipe, 4096)
            while True:
                try:
                    kind, pkg = self.events.get_nowait()
                except queue.Empty:
                    break
                self._handle_incoming(inj, kind, pkg, buttons, stats)
            inj.flush()
            now = time.monotonic()
            if self._cap is not None and now - last_edges > 2:
                self.refresh_edges(self._cap)
                inj.flush()
                last_edges = now
            if now - last_log > 60 and (stats["mouse"] or stats["key"]):
                log.info("eventos/min: mouse=%d teclado=%d", stats["mouse"], stats["key"])
                stats = {"mouse": 0, "key": 0}
                last_log = now


def _signed16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def main(argv=None):
    ap = argparse.ArgumentParser(prog="owb run", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default="~/.config/owb/config.json")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--no-inject", action="store_true", help="só rede (teste de handshake sem Wayland)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname).1s %(message)s", datefmt="%H:%M:%S")
    cfg = Config(args.config)
    if cfg.data.get("language", "auto") != "auto":
        set_language(cfg.data["language"])
    if len(cfg.key.replace(" ", "")) < 16:
        log.error("chave não configurada — rode: owb setup   (config em %s)", cfg.path)
        sys.exit(2)
    d = Daemon(cfg)
    if cfg.listen:
        threading.Thread(target=d.listener_loop, name="listener", daemon=True).start()
    threading.Thread(target=d.connector_loop, name="connector", daemon=True).start()
    threading.Thread(target=d.heartbeat_loop, name="heartbeat", daemon=True).start()
    threading.Thread(target=d.control_loop, name="control", daemon=True).start()
    if cfg.data.get("share_clipboard", True):
        threading.Thread(target=d.clipboard_watch_loop, name="clipwatch", daemon=True).start()
    if args.no_inject:
        while True:
            kind, pkg = d.events.get()
            if kind == "mouse":
                log.info("mouse x=%d y=%d flags=0x%X wheel=%d", pkg.mx, pkg.my, pkg.mflags, pkg.wheel)
            elif kind == "key":
                log.info("key vk=0x%02X flags=0x%X", pkg.vk, pkg.kflags)
    else:
        d.main_loop()


if __name__ == "__main__":
    main()
