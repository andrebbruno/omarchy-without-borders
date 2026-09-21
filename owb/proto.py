"""Protocolo do Mouse Without Borders (PowerToys) — formato de pacotes e criptografia.

Reimplementação fiel de DATA.cs / Package.cs / Encryption.cs / SocketStuff.TcpSendData
(fonte MIT: src/modules/MouseWithoutBorders/App). Tudo little-endian.
"""
from __future__ import annotations

import hashlib
import os
import struct
from enum import IntEnum

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

PACKAGE_SIZE = 32
PACKAGE_SIZE_EX = 64
BLOCK = 16
SALT_SIZE = 16
KDF_ITERATIONS = 100_000
KEY_LEN = 32

ID_NONE = 0
ID_ALL = 255


class PackageType(IntEnum):
    Invalid = 0xFF
    Error = 0xFE
    Hi = 2
    Hello = 3
    ByeBye = 4
    Heartbeat = 20
    Awake = 21
    HideMouse = 50
    Heartbeat_ex = 51
    Heartbeat_ex_l2 = 52
    Heartbeat_ex_l3 = 53
    Clipboard = 69
    ClipboardDragDrop = 70
    ClipboardDragDropEnd = 71
    ExplorerDragDrop = 72
    ClipboardCapture = 73
    CaptureScreenCommand = 74
    ClipboardDragDropOperation = 75
    ClipboardDataEnd = 76
    MachineSwitched = 77
    ClipboardAsk = 78
    ClipboardPush = 79
    NextMachine = 121
    Keyboard = 122
    Mouse = 123
    ClipboardText = 124
    ClipboardImage = 125
    Handshake = 126
    HandshakeAck = 127
    Matrix = 128


BIG_TYPES = {
    PackageType.Hello, PackageType.Awake, PackageType.Heartbeat, PackageType.Heartbeat_ex,
    PackageType.Handshake, PackageType.HandshakeAck, PackageType.ClipboardPush,
    PackageType.Clipboard, PackageType.ClipboardAsk, PackageType.ClipboardImage,
    PackageType.ClipboardText, PackageType.ClipboardDataEnd,
}


def is_big(ptype: int) -> bool:
    return ptype in BIG_TYPES or (ptype & PackageType.Matrix) == PackageType.Matrix


# Windows messages usadas em MOUSEDATA.dwFlags e flags de KEYBDDATA
WM_MOUSEMOVE = 0x200
WM_LBUTTONDOWN, WM_LBUTTONUP = 0x201, 0x202
WM_RBUTTONDOWN, WM_RBUTTONUP = 0x204, 0x205
WM_MBUTTONDOWN, WM_MBUTTONUP = 0x207, 0x208
WM_XBUTTONDOWN, WM_XBUTTONUP = 0x20B, 0x20C
WM_MOUSEWHEEL, WM_MOUSEHWHEEL = 0x20A, 0x20E
LLKHF_EXTENDED, LLKHF_UP = 0x01, 0x80


class Package:
    """Espelho da union DATA. Campos em offsets fixos; MachineName em 32..64."""

    __slots__ = ("buf",)

    def __init__(self, buf: bytes | None = None):
        self.buf = bytearray(PACKAGE_SIZE_EX)
        if buf:
            self.buf[: len(buf)] = buf

    # -- cabeçalho --
    @property
    def type(self) -> int:
        return self.buf[0]

    @type.setter
    def type(self, v: int):
        self.buf[0] = v & 0xFF

    def _u32(self, off):
        return struct.unpack_from("<I", self.buf, off)[0]

    def _set_u32(self, off, v):
        struct.pack_into("<I", self.buf, off, v & 0xFFFFFFFF)

    def _i32(self, off):
        return struct.unpack_from("<i", self.buf, off)[0]

    def _set_i32(self, off, v):
        struct.pack_into("<i", self.buf, off, v)

    id = property(lambda s: s._i32(4), lambda s, v: s._set_i32(4, v))
    src = property(lambda s: s._u32(8), lambda s, v: s._set_u32(8, v))
    des = property(lambda s: s._u32(12), lambda s, v: s._set_u32(12, v))

    # -- MOUSEDATA @16: X, Y, WheelDelta, dwFlags --
    mx = property(lambda s: s._i32(16), lambda s, v: s._set_i32(16, v))
    my = property(lambda s: s._i32(20), lambda s, v: s._set_i32(20, v))
    wheel = property(lambda s: s._i32(24), lambda s, v: s._set_i32(24, v))
    mflags = property(lambda s: s._i32(28), lambda s, v: s._set_i32(28, v))

    # -- KEYBDDATA @24: wVk, dwFlags --
    vk = property(lambda s: s._i32(24), lambda s, v: s._set_i32(24, v))
    kflags = property(lambda s: s._i32(28), lambda s, v: s._set_i32(28, v))

    # -- Machine1..4 @16,20,24,28 (handshake) --
    def machines(self):
        return tuple(self._u32(16 + 4 * i) for i in range(4))

    def set_machines(self, vals):
        for i, v in enumerate(vals):
            self._set_u32(16 + 4 * i, v)

    def invert_machines(self):
        self.set_machines(tuple((~v) & 0xFFFFFFFF for v in self.machines()))

    # -- MachineName @32..64 (32 chars, padded com espaço) --
    @property
    def machine_name(self) -> str:
        return self.buf[32:64].decode("latin-1", "replace").strip()

    @machine_name.setter
    def machine_name(self, name: str):
        self.buf[32:64] = name.ljust(32)[:32].encode("latin-1", "replace")

    @property
    def is_big(self) -> bool:
        return is_big(self.type)

    def wire(self) -> bytes:
        return bytes(self.buf[: PACKAGE_SIZE_EX if self.is_big else PACKAGE_SIZE])


# ---------------------------------------------------------------- criptografia

def magic_number(key: str) -> int:
    """Encryption.Get24BitHash: SHA-512 iterado 50 000x sobre buffer de 32 bytes."""
    buf = bytearray(PACKAGE_SIZE)
    for i, ch in enumerate(key[:PACKAGE_SIZE]):
        buf[i] = ord(ch) & 0xFF
    h = hashlib.sha512(bytes(buf)).digest()
    for _ in range(50_000):
        h = hashlib.sha512(h).digest()
    return ((h[0] << 23) + (h[1] << 16) + (h[-1] << 8) + h[2]) & 0xFFFFFFFF


LEGACY_IV_STR = str(2**64 - 1)  # "18446744073709551615" (ulong.MaxValue)


def derive_key(shared_key: str, salt: bytes, iterations: int = KDF_ITERATIONS) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA512(), length=KEY_LEN, salt=salt, iterations=iterations)
    return kdf.derive(shared_key.encode("utf-8"))


def legacy_key_iv(shared_key: str) -> tuple[bytes, bytes]:
    """PowerToys <= 0.100.x: salt fixo (UTF-16LE do InitialIV, 50 000 it.) e IV fixo (ASCII, 16 B)."""
    key = derive_key(shared_key, LEGACY_IV_STR.encode("utf-16-le"), 50_000)
    iv = LEGACY_IV_STR.encode("ascii")[:BLOCK].ljust(BLOCK, b" ")
    return key, iv


def seal(buf: bytearray, magic: int) -> None:
    """TcpSendData: grava magic nos bytes 2-3 e checksum no byte 1 (sobre bytes 2..31)."""
    buf[3] = (magic >> 24) & 0xFF
    buf[2] = (magic >> 16) & 0xFF
    buf[1] = sum(buf[2:PACKAGE_SIZE]) & 0xFF


def unseal(buf: bytearray, magic: int) -> bool:
    """ProcessReceivedDataEx: valida magic e checksum, zera bytes 1-3. Retorna válido?"""
    ok = True
    got_magic = (buf[3] << 24) + (buf[2] << 16)
    if got_magic != (magic & 0xFFFF0000):
        ok = False
    if buf[1] != (sum(buf[2:PACKAGE_SIZE]) & 0xFF):
        ok = False
    buf[1] = buf[2] = buf[3] = 0
    return ok


class Encryptor:
    """Lado de escrita de um socket.

    legacy=True  (PowerToys lançado, <= 0.100.x): sem header; chave/IV fixos derivados da chave.
    legacy=False (main): header salt+IV em claro, chave derivada por conexão.
    Em ambos, o primeiro bloco cifrado é 16 B aleatórios descartados pelo receptor.
    """

    def __init__(self, shared_key: str, legacy: bool = True):
        self.legacy = legacy
        if legacy:
            key, iv = legacy_key_iv(shared_key)
            self.salt, self.iv = b"", iv
        else:
            self.salt = os.urandom(SALT_SIZE)
            self.iv = os.urandom(BLOCK)
            key = derive_key(shared_key, self.salt)
        self._enc = Cipher(algorithms.AES(key), modes.CBC(self.iv)).encryptor()

    def header(self) -> bytes:
        return b"" if self.legacy else self.salt + self.iv

    def encrypt(self, data: bytes) -> bytes:
        assert len(data) % BLOCK == 0
        return self._enc.update(data)

    def initial_block(self) -> bytes:
        return self.encrypt(os.urandom(BLOCK))


class Decryptor:
    HEADER_LEN = SALT_SIZE + BLOCK  # só no modo salted

    def __init__(self, shared_key: str, header: bytes = b"", legacy: bool = True):
        if legacy:
            key, iv = legacy_key_iv(shared_key)
        else:
            salt, iv = header[:SALT_SIZE], header[SALT_SIZE:SALT_SIZE + BLOCK]
            key = derive_key(shared_key, salt)
        self._dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()

    def decrypt(self, data: bytes) -> bytes:
        assert len(data) % BLOCK == 0
        return self._dec.update(data)
