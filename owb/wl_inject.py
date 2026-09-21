"""Injeção de mouse/teclado no Wayland via zwlr_virtual_pointer_v1 e zwp_virtual_keyboard_v1.

Não precisa de root nem de uinput: o compositor (Hyprland/wlroots) expõe os protocolos.
Deve ser usado por uma única thread (o Display do pywayland não é thread-safe).
"""
from __future__ import annotations

import os
import sys
import time

from pywayland.client import Display
from pywayland.protocol.wayland import WlSeat

from .wl.hyprland_input_capture_v1 import HyprlandInputCaptureManagerV1
from .wl.virtual_keyboard_unstable_v1 import ZwpVirtualKeyboardManagerV1
from .wl.wlr_virtual_pointer_unstable_v1 import ZwlrVirtualPointerManagerV1

BTN_LEFT, BTN_RIGHT, BTN_MIDDLE, BTN_SIDE, BTN_EXTRA = 0x110, 0x111, 0x112, 0x113, 0x114
AXIS_V, AXIS_H = 0, 1
XKB_V1 = 1


def _now_ms() -> int:
    return int(time.monotonic() * 1000) & 0xFFFFFFFF


class WaylandInjector:
    def __init__(self, layout: str = "br", variant: str = "", model: str = "pc105"):
        self.display = Display()
        self.display.connect()
        self.seat = None
        self.vp_mgr = None
        self.vk_mgr = None
        self.capture_mgr = None
        reg = self.display.get_registry()
        reg.dispatcher["global"] = self._on_global
        self.display.roundtrip()
        missing = [n for n, o in (("wl_seat", self.seat), ("zwlr_virtual_pointer_manager_v1", self.vp_mgr),
                                  ("zwp_virtual_keyboard_manager_v1", self.vk_mgr)) if o is None]
        if missing:
            raise RuntimeError(f"compositor não expõe: {', '.join(missing)}")
        self.pointer = self.vp_mgr.create_virtual_pointer(self.seat)
        self.keyboard = self.vk_mgr.create_virtual_keyboard(self.seat)
        self._upload_keymap(layout, variant, model)
        self.display.roundtrip()
        self._pressed: set[int] = set()

    def _on_global(self, registry, id_, interface, version):
        if interface == "wl_seat" and self.seat is None:
            self.seat = registry.bind(id_, WlSeat, min(version, 7))
        elif interface == "zwlr_virtual_pointer_manager_v1":
            self.vp_mgr = registry.bind(id_, ZwlrVirtualPointerManagerV1, min(version, 2))
        elif interface == "zwp_virtual_keyboard_manager_v1":
            self.vk_mgr = registry.bind(id_, ZwpVirtualKeyboardManagerV1, 1)
        elif interface == "hyprland_input_capture_manager_v1":
            self.capture_mgr = registry.bind(id_, HyprlandInputCaptureManagerV1, min(version, 2))

    def _upload_keymap(self, layout, variant, model):
        from xkbcommon import xkb
        ctx = xkb.Context()
        keymap = ctx.keymap_new_from_names(rules="evdev", model=model, layout=layout, variant=variant)
        data = keymap.get_as_string().encode() + b"\0"
        fd = os.memfd_create("mwb-keymap")
        os.write(fd, data)
        self.keyboard.keymap(XKB_V1, fd, len(data))
        os.close(fd)

    # ------------------------------------------------------------ mouse
    def move_abs(self, x: int, y: int, extent: int = 65535):
        """Coordenadas absolutas normalizadas (MWB usa 0..65535 sobre a tela)."""
        x = max(0, min(extent, x))
        y = max(0, min(extent, y))
        self.pointer.motion_absolute(_now_ms(), x, y, extent, extent)
        self.pointer.frame()

    def move_rel(self, dx: int, dy: int):
        self.pointer.motion(_now_ms(), float(dx), float(dy))
        self.pointer.frame()

    def button(self, btn: int, pressed: bool):
        self.pointer.button(_now_ms(), btn, 1 if pressed else 0)
        self.pointer.frame()

    def wheel(self, delta: int, horizontal: bool = False):
        """delta no padrão Windows (±120 por dente; positivo = para cima/esquerda)."""
        axis = AXIS_H if horizontal else AXIS_V
        notches = delta / 120.0
        # Wayland: valor positivo = para baixo / direita
        value = -notches * 15.0 if not horizontal else notches * 15.0
        self.pointer.axis_source(0)  # wheel
        self.pointer.axis_discrete(_now_ms(), axis, value, int(round(-notches if not horizontal else notches)))
        self.pointer.frame()

    # ------------------------------------------------------------ teclado
    def key(self, keycode: int, pressed: bool):
        if pressed:
            self._pressed.add(keycode)
        else:
            self._pressed.discard(keycode)
        self.keyboard.key(_now_ms(), keycode, 1 if pressed else 0)

    def release_all(self):
        for kc in list(self._pressed):
            self.keyboard.key(_now_ms(), kc, 0)
        self._pressed.clear()
        self.flush()

    def flush(self):
        self.display.flush()

    def fileno(self) -> int:
        return self.display.get_fd()

    def dispatch_pending(self):
        """Processa eventos já chegados no socket Wayland (chamar quando o fd estiver legível)."""
        self.display.read()
        self.display.dispatch(block=False)
        self.display.flush()

    def close(self):
        try:
            self.release_all()
        finally:
            self.display.disconnect()
