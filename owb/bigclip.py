"""Big clipboard and file transfer over MWB's base port (15100).

MWB sends clipboard data inline (ClipboardText/ClipboardImage packets) only up to 1 MB. Above
that, and for files, the machine that copied just broadcasts a `Clipboard` beat; whoever becomes
the active machine within 30 s (MachineSwitched / switching back to itself) fetches the data
through a dedicated TCP connection on the *base* port:

  client                                   server (port 15100)
  ------ 16 random bytes (encrypted) ----->
  ------ 64-byte header package ---------->   Type = Clipboard (pull) | ClipboardPush (push)
  <----- 16 random bytes (encrypted) ------
  <----- 64-byte header package -----------   Type = ClipboardPush (always), Src = server id
  then the sender writes a 1024-byte UTF-16LE header "<size>*<text|image|C:\\path\\file>"
  followed by <size> bytes of payload (zero-padded to a block), and closes.

Same cipher as the message channel (continuous AES-CBC, first block discarded). A machine that
cannot connect to the owner (outbound-only firewall) sends `ClipboardAsk`; the owner then
connects to it and pushes (Type = ClipboardPush). Formats are the inline ones: text is
UTF-16LE "TXT…SEP" raw-deflated, image is PNG; files are raw bytes (MWB limit: 100 MB).
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import threading
import time

from . import clipboard as C
from . import proto as P
from .i18n import t

log = logging.getLogger("bigclip")

BEAT_TIMEOUT = 30.0                    # Clipboard.BIG_CLIPBOARD_DATA_TIMEOUT
MAX_FILE = 100 * 1024 * 1024           # MAX_CLIPBOARD_FILE_SIZE_CAN_BE_SENT
HEADER_LEN = 1024
BUF = 1024 * 1024


def received_dir() -> str:
    """Where received files go: $XDG_DOWNLOAD_DIR/OmarchyWithoutBorders (or ~/Downloads/...)."""
    base = None
    try:
        base = subprocess.run(["xdg-user-dir", "DOWNLOAD"], capture_output=True, text=True, timeout=2).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    if not base or not os.path.isdir(base):
        base = os.path.expanduser("~/Downloads")
    return os.path.join(base, "OmarchyWithoutBorders")


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1] or "file"


class _Stream:
    """Encrypted duplex stream on one socket (block-aligned reads/writes)."""

    def __init__(self, sock: socket.socket, key: str, legacy: bool):
        self.sock = sock
        self.legacy = legacy
        self.enc = P.Encryptor(key, legacy=legacy)
        self.dec: P.Decryptor | None = None
        self.key = key
        self._pending = b""

    def open(self, header_pkg: P.Package):
        """ShakeHand: write our side, then read the remote header package."""
        self.sock.settimeout(30)
        self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if not self.legacy:
            self.sock.sendall(self.enc.header())
        self.sock.sendall(self.enc.initial_block())
        self.write(header_pkg.buf[:P.PACKAGE_SIZE_EX])
        hdr = b"" if self.legacy else self._recv_exact(P.Decryptor.HEADER_LEN)
        self.dec = P.Decryptor(self.key, hdr, legacy=self.legacy)
        self.read_exact(P.BLOCK)
        return P.Package(bytearray(self.read_exact(P.PACKAGE_SIZE_EX)))

    def write(self, data: bytes):
        pad = (-len(data)) % P.BLOCK
        self.sock.sendall(self.enc.encrypt(data + b"\0" * pad))

    def _recv_exact(self, n: int) -> bytes:
        out = bytearray()
        while len(out) < n:
            chunk = self.sock.recv(n - len(out))
            if not chunk:
                raise ConnectionError("connection closed")
            out += chunk
        return bytes(out)

    def read_exact(self, n: int) -> bytes:
        return self.dec.decrypt(self._recv_exact(n))

    def read_some(self, max_bytes: int = BUF) -> bytes:
        """Decrypt whatever arrived (whole blocks only); b'' at EOF."""
        while True:
            chunk = self.sock.recv(max_bytes)
            if not chunk:
                return b""
            data = self._pending + chunk
            cut = len(data) - len(data) % P.BLOCK
            self._pending = data[cut:]
            if cut:
                return self.dec.decrypt(data[:cut])

    def close(self):
        try:
            self.sock.close()
        except OSError:
            pass


class BigClipboard:
    def __init__(self, daemon):
        self.d = daemon
        self.legacy = daemon.cfg.crypto != "salted"
        self.pending: tuple[int, str, float] | None = None   # (src id, name, when) from a Clipboard beat
        self.local: tuple[str, bytes | str] | None = None    # ("text"|"image", data) | ("file", path)
        self._lock = threading.Lock()

    # ------------------------------------------------------------ message-channel side
    def beat_received(self, src: int, name: str):
        self.pending = (src, name, time.monotonic())
        log.info("%s has a big clipboard/file — will fetch when this machine becomes active", name)

    def machine_switched_to_me(self):
        """MachineSwitched(des=me) or returning from host mode: fetch pending data (like MWB)."""
        p = self.pending
        if not p or time.monotonic() - p[2] > BEAT_TIMEOUT:
            return
        self.pending = None
        threading.Thread(target=self._fetch, args=(p[0], p[1]), name="bigclip-fetch", daemon=True).start()

    def ask_received(self, src: int, name: str):
        """ClipboardAsk(des=me): the other side cannot reach our port; connect and push."""
        threading.Thread(target=self._push, args=(src, name), name="bigclip-push", daemon=True).start()

    def announce(self, kind: str, payload):
        """Keep data for pulls and broadcast a Clipboard beat."""
        with self._lock:
            self.local = (kind, payload)
        n = 0
        for p in self.d.trusted_peers_by_name().values():
            try:
                p.send_typed(P.PackageType.Clipboard)
                n += 1
            except OSError:
                pass
        log.info("clipboard beat -> %d machine(s): %s", n, self._describe(kind, payload))

    # ------------------------------------------------------------ server on the base port
    def server_loop(self):
        srv = self.d.listen_socket(self.d.cfg.port)
        log.info("clipboard/file server on port %d", self.d.cfg.port)
        while True:
            s, addr = srv.accept()
            threading.Thread(target=self._serve, args=(s, addr[0].replace("::ffff:", "")),
                             name="bigclip-serve", daemon=True).start()

    def _serve(self, sock: socket.socket, ip: str):
        st = _Stream(sock, self.d.key, self.legacy)
        try:
            remote = st.open(self._header(P.PackageType.ClipboardPush))
            name = remote.machine_name
            if remote.type not in (P.PackageType.Clipboard, P.PackageType.ClipboardPush) or not self._known(remote.src, name):
                log.warning("clipboard connection from %s (%s) rejected: unknown machine or bad key", ip, name)
                return
            if remote.type == P.PackageType.ClipboardPush:
                self._receive(st, name)
            else:
                self._send(st, name)
        except (OSError, ConnectionError, ValueError) as e:
            log.warning("clipboard connection from %s failed: %s", ip, e)
        finally:
            st.close()

    # ------------------------------------------------------------ client side
    def _fetch(self, src: int, name: str):
        peer = self.d.peer_by_name(name)
        if peer is None:
            return
        addr = self._client_addr(name)
        if addr is None:
            log.info("no outbound connection to %s — asking it to push", name)
            pkg = P.Package()
            pkg.type = P.PackageType.ClipboardAsk
            pkg.des = src
            pkg.id = self.d.next_id()
            pkg.machine_name = self.d.machine_name
            try:
                peer.send(pkg)
            except OSError as e:
                log.warning("ClipboardAsk -> %s failed: %s", name, e)
            return
        st = None
        try:
            sock = socket.create_connection((addr, self.d.cfg.port), timeout=10)
            st = _Stream(sock, self.d.key, self.legacy)
            st.open(self._header(P.PackageType.Clipboard))
            self._receive(st, name)
        except (OSError, ConnectionError, ValueError) as e:
            log.warning("fetching clipboard from %s (%s) failed: %s", name, addr, e)
        finally:
            if st:
                st.close()

    def _push(self, src: int, name: str):
        addr = self._client_addr(name) or self._any_addr(name)
        if addr is None:
            log.warning("ClipboardAsk from %s but no address for it", name)
            return
        st = None
        try:
            sock = socket.create_connection((addr, self.d.cfg.port), timeout=10)
            st = _Stream(sock, self.d.key, self.legacy)
            st.open(self._header(P.PackageType.ClipboardPush))
            self._send(st, name)
        except (OSError, ConnectionError, ValueError) as e:
            log.warning("pushing clipboard to %s (%s) failed: %s", name, addr, e)
        finally:
            if st:
                st.close()

    # ------------------------------------------------------------ payload
    def _send(self, st: _Stream, name: str):
        with self._lock:
            local = self.local
        if not local:
            log.info("%s asked for our big clipboard but there is none", name)
            return
        kind, payload = local
        if kind == "file":
            path = str(payload)
            if not os.path.isfile(path):
                st.write(self._hdr(0, f"{path} not found!"))
                return
            size = os.path.getsize(path)
            st.write(self._hdr(size, path))
            with open(path, "rb") as f:
                sent = 0
                while True:
                    chunk = f.read(BUF)
                    if not chunk:
                        break
                    st.write(chunk)
                    sent += len(chunk)
        else:
            data = bytes(payload)
            st.write(self._hdr(len(data), kind))
            for i in range(0, len(data), BUF):
                st.write(data[i:i + BUF])
        st.write(b"\0" * P.PACKAGE_SIZE_EX)     # like SendFileEx: make sure the last block is flushed
        log.info("clipboard -> %s: %s", name, self._describe(kind, payload))

    def _receive(self, st: _Stream, name: str):
        head = st.read_exact(HEADER_LEN).decode("utf-16-le", "replace").split("\0", 1)[0]
        size_s, _, label = head.partition("*")
        try:
            size = int(size_s)
        except ValueError:
            raise ValueError(f"bad header {head!r}")
        if size <= 0:
            log.warning("%s: %s", name, label)
            self.d.notify(t("d.clip_error", name=name), label, "normal")
            return
        low = label.lower()
        to_file = not (low.startswith("text") or low.startswith("image"))
        if to_file:
            os.makedirs(received_dir(), exist_ok=True)
            dest = os.path.join(received_dir(), _basename(label))
            out = open(dest + ".part", "wb")
        else:
            out = bytearray()
        got = 0
        try:
            while got < size:
                chunk = st.read_some()
                if not chunk:
                    break
                if got + len(chunk) > size:
                    chunk = chunk[:size - got]
                if to_file:
                    out.write(chunk)
                else:
                    out += chunk
                got += len(chunk)
        finally:
            if to_file:
                out.close()
        if got < size:
            if to_file:
                os.unlink(dest + ".part")
            raise ConnectionError(f"incomplete: {got}/{size} bytes")
        if to_file:
            os.replace(dest + ".part", dest)
            C.set_uri_list([dest])
            self.d.clip_last = ("file", dest)
            log.info("file <- %s: %s (%d B)", name, dest, size)
            self.d.notify(t("d.file_received", name=name), dest, "normal")
        elif low.startswith("image"):
            C.set_image_png(bytes(out))
            self.d.clip_last = ("image", bytes(out))
            log.info("clipboard <- %s: image (%d B)", name, size)
        else:
            txt = C.decode_text(bytes(out)).get("TXT")
            if txt is not None:
                C.set_text(txt)
                self.d.clip_last_text = txt
                log.info("clipboard <- %s: %d chars", name, len(txt))
        self.d.clip_suppress_until = time.monotonic() + 1.5

    # ------------------------------------------------------------ helpers
    def _header(self, ptype: int) -> P.Package:
        pkg = P.Package()
        pkg.type = ptype
        pkg.src = self.d.machine_id
        pkg.des = P.ID_ALL
        pkg.machine_name = self.d.machine_name
        return pkg

    @staticmethod
    def _hdr(size: int, label: str) -> bytes:
        b = f"{size}*{label}".encode("utf-16-le")[:HEADER_LEN]
        return b + b"\0" * (HEADER_LEN - len(b))

    def _known(self, src: int, name: str) -> bool:
        p = self.d.peer_by_name(name)
        return p is not None and p.remote_id == src

    def _client_addr(self, name: str):
        """IP of a connection *we* dialled to that machine (so its base port is reachable)."""
        with self.d.peers_lock:
            for p in reversed(self.d.peers):
                if p.alive and p.trusted and p.is_client and p.remote_name.upper() == name.upper():
                    try:
                        return p.sock.getpeername()[0]
                    except OSError:
                        continue
        return None

    def _any_addr(self, name: str):
        p = self.d.peer_by_name(name)
        try:
            return p.sock.getpeername()[0] if p else None
        except OSError:
            return None

    @staticmethod
    def _describe(kind: str, payload) -> str:
        if kind == "file":
            return f"file {payload}"
        return f"{kind} {len(payload)} B"
