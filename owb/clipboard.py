"""Clipboard compartilhado no formato do MWB (texto/imagem <= 1 MB via socket de mensagens).

Texto: "TXT"+texto+SEP [+"RTF"…SEP] [+"HTM"…SEP], UTF-16LE, Deflate cru, fatiado em 48 B.
Imagem: PNG bruto, mesma fatia. Lado Linux usa wl-copy / wl-paste (wl-clipboard).
"""
from __future__ import annotations

import logging
import os
import subprocess
import zlib

log = logging.getLogger("clipboard")

SEP = "{4CFF57F7-BEDD-43d5-AE8F-27A61E886F2F}"
DATA_SIZE = 48
DATA_START = 64 - DATA_SIZE
MAX_INLINE = 1024 * 1024


def encode_text(text: str, html: str | None = None) -> bytes:
    st = "TXT" + text + SEP
    if html:
        st += "HTM" + html + SEP
    raw = st.encode("utf-16-le")
    c = zlib.compressobj(6, zlib.DEFLATED, -15)
    return c.compress(raw) + c.flush()


def decode_text(data: bytes) -> dict[str, str]:
    """Devolve {'TXT': ..., 'RTF': ..., 'HTM': ...} (os presentes)."""
    d = zlib.decompressobj(-15)
    raw = d.decompress(data)
    st = raw.decode("utf-16-le", "replace")
    out = {}
    for part in st.split(SEP):
        part = part.strip("\0")
        if len(part) > 3 and part[:3].upper() in ("TXT", "RTF", "HTM"):
            out[part[:3].upper()] = part[3:]
    return out


def chunks(data: bytes):
    """Fatias de 48 B (a última preenchida com zeros), como SendClipboardDataUsingTCP."""
    for i in range(0, len(data), DATA_SIZE):
        piece = data[i:i + DATA_SIZE]
        yield piece + b"\0" * (DATA_SIZE - len(piece))


# ---------------------------------------------------------------- lado Linux (wl-clipboard)

def _env():
    e = dict(os.environ)
    e.setdefault("WAYLAND_DISPLAY", "wayland-1")
    return e


def set_text(text: str):
    subprocess.run(["wl-copy", "--type", "text/plain;charset=utf-8"], input=text.encode("utf-8"), env=_env(), check=False)


def set_image_png(png: bytes):
    subprocess.run(["wl-copy", "--type", "image/png"], input=png, env=_env(), check=False)


def get_types() -> list[str]:
    r = subprocess.run(["wl-paste", "--list-types"], capture_output=True, env=_env(), check=False)
    return r.stdout.decode(errors="replace").split()


def get_text() -> str | None:
    r = subprocess.run(["wl-paste", "--no-newline", "--type", "text"], capture_output=True, env=_env(), check=False)
    return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else None


def get_image_png() -> bytes | None:
    r = subprocess.run(["wl-paste", "--type", "image/png"], capture_output=True, env=_env(), check=False)
    return r.stdout if r.returncode == 0 and r.stdout else None


WATCH_SCRIPT = r'''#!/bin/sh
# chamado pelo wl-paste --watch a cada mudança do clipboard; avisa o daemon
printf 'clipchange\n' | socat -T1 - UNIX-CONNECT:/tmp/mwbd.sock 2>/dev/null || \
python3 -c 'import socket;s=socket.socket(socket.AF_UNIX);s.connect("/tmp/mwbd.sock");s.sendall(b"clipchange\n")'
'''
