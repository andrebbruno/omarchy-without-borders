"""A minimal Windows-side MWB emulator for end-to-end tests of the big clipboard / file path.

Connects to a running owb daemon (message port), completes the MWB handshake, announces a big
clipboard (Clipboard beat), tells the daemon it became the active machine (MachineSwitched) and,
when the daemon answers with ClipboardAsk (it has no outbound connection to us), connects to the
daemon's base port and pushes a file/text exactly like PowerToys' ClipboardAsk handler.

    python tests/fake_mwb.py HOST KEY --file some.bin      # or --text N (N random chars)

Only the legacy (released PowerToys) cipher is emulated.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import os
import random
import socket
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from owb import clipboard as C  # noqa: E402
from owb import proto as P  # noqa: E402

NAME = "FAKE-WIN"
MID = 424242


class Chan:
    def __init__(self, sock, key):
        self.sock = sock
        self.magic = P.magic_number(key)
        self.enc = P.Encryptor(key, legacy=True)
        self.dec = P.Decryptor(key, legacy=True)
        sock.sendall(self.enc.initial_block())
        self._skip = P.BLOCK

    def send(self, pkg: P.Package):
        pkg.src = MID
        buf = bytearray(pkg.wire())
        P.seal(buf, self.magic)
        self.sock.sendall(self.enc.encrypt(bytes(buf)))

    def _exact(self, n):
        out = b""
        while len(out) < n:
            c = self.sock.recv(n - len(out))
            if not c:
                raise ConnectionError
            out += c
        return out

    def recv(self) -> P.Package:
        if self._skip:
            self.dec.decrypt(self._exact(self._skip))
            self._skip = 0
        buf = bytearray(self.dec.decrypt(self._exact(P.PACKAGE_SIZE)))
        P.unseal(buf, self.magic)
        pkg = P.Package(buf)
        if pkg.is_big:
            pkg.buf[P.PACKAGE_SIZE:] = self.dec.decrypt(self._exact(P.PACKAGE_SIZE))
        return pkg


def typed(t, des=P.ID_ALL):
    p = P.Package()
    p.type, p.des, p.id = t, des, random.randint(1, 1 << 30)
    p.machine_name = NAME
    return p


def push(host, port, key, label, data: bytes):
    """ClipboardAsk handler: connect to the asker's base port, ShakeHand with ClipboardPush, send."""
    s = socket.create_connection((host, port), timeout=30)
    enc, dec = P.Encryptor(key, legacy=True), P.Decryptor(key, legacy=True)
    s.sendall(enc.initial_block())
    hdr = typed(P.PackageType.ClipboardPush)
    hdr.src = MID
    s.sendall(enc.encrypt(bytes(hdr.buf[:64])))
    # remote: 16 random + 64 header
    got = b""
    while len(got) < 80:
        got += s.recv(80 - len(got))
    remote = P.Package(bytearray(dec.decrypt(got)[16:]))
    print("server header:", P.PackageType(remote.type).name, remote.machine_name, remote.src)
    head = f"{len(data)}*{label}".encode("utf-16-le")
    s.sendall(enc.encrypt(head + b"\0" * (1024 - len(head))))
    pad = (-len(data)) % 64 or 64
    s.sendall(enc.encrypt(data + b"\0" * pad))
    s.close()
    print(f"pushed {len(data)} bytes as {label!r}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("key")
    ap.add_argument("--port", type=int, default=15100)
    ap.add_argument("--file")
    ap.add_argument("--text", type=int, default=0)
    a = ap.parse_args()

    if a.file:
        data = open(a.file, "rb").read()
        label = "C:\\Users\\fake\\Desktop\\" + os.path.basename(a.file)
    else:
        txt = "FAKE-BIG " + base64.b64encode(os.urandom(a.text * 3 // 4)).decode()
        data, label = C.encode_text(txt), "text"
        print("text md5:", hashlib.md5(txt.encode()).hexdigest(), "chars:", len(txt))
    print("payload md5:", hashlib.md5(data).hexdigest(), "bytes:", len(data))

    s = socket.create_connection((a.host, a.port + 1), timeout=30)
    ch = Chan(s, a.key)
    hs = P.Package(os.urandom(64))
    hs.type = P.PackageType.Handshake
    hs.machine_name = NAME
    for _ in range(10):
        ch.send(hs)
    hs.invert_machines()
    challenge = hs.machines()
    trusted = False
    deadline = time.time() + 20
    while time.time() < deadline:
        pkg = ch.recv()
        t = pkg.type
        if t == P.PackageType.Handshake:
            ack = P.Package(pkg.buf)
            ack.type = P.PackageType.HandshakeAck
            ack.machine_name = NAME
            ack.invert_machines()
            ch.send(ack)
        elif t == P.PackageType.HandshakeAck and pkg.machines() == challenge:
            trusted = True
            print("trusted by", pkg.machine_name, pkg.src)
            ch.send(typed(P.PackageType.Heartbeat))
            break
    if not trusted:
        sys.exit("handshake failed")
    time.sleep(1)
    ch.send(typed(P.PackageType.Clipboard))               # "I have a big clipboard"
    time.sleep(0.5)
    ch.send(typed(P.PackageType.MachineSwitched, pkg.src))  # "you are now the active machine"
    print("beat + MachineSwitched sent; waiting for ClipboardAsk")
    deadline = time.time() + 20
    while time.time() < deadline:
        pkg = ch.recv()
        if pkg.type == P.PackageType.ClipboardAsk and pkg.des == MID:
            print("ClipboardAsk from", pkg.machine_name)
            push(a.host, a.port, a.key, label, data)
            break
    else:
        sys.exit("no ClipboardAsk received")
    time.sleep(1)
    s.close()


if __name__ == "__main__":
    main()
