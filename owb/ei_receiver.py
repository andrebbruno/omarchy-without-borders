"""Receptor libei (ctypes) — lê os eventos do socket EIS que o Hyprland entrega
quando a captura de entrada está ativa (hyprland_input_capture_v1.eis_fd).
"""
from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass

_lib = ctypes.CDLL(ctypes.util.find_library("ei") or "libei.so.1")

# tipos opacos
_p = ctypes.c_void_p
_lib.ei_new_receiver.restype = _p
_lib.ei_new_receiver.argtypes = [_p]
_lib.ei_configure_name.argtypes = [_p, ctypes.c_char_p]
_lib.ei_setup_backend_fd.restype = ctypes.c_int
_lib.ei_setup_backend_fd.argtypes = [_p, ctypes.c_int]
_lib.ei_get_fd.restype = ctypes.c_int
_lib.ei_get_fd.argtypes = [_p]
_lib.ei_dispatch.argtypes = [_p]
_lib.ei_get_event.restype = _p
_lib.ei_get_event.argtypes = [_p]
_lib.ei_event_unref.restype = _p
_lib.ei_event_unref.argtypes = [_p]
_lib.ei_event_get_type.restype = ctypes.c_int
_lib.ei_event_get_type.argtypes = [_p]
_lib.ei_event_get_seat.restype = _p
_lib.ei_event_get_seat.argtypes = [_p]
_lib.ei_event_get_device.restype = _p
_lib.ei_event_get_device.argtypes = [_p]
_lib.ei_device_get_name.restype = ctypes.c_char_p
_lib.ei_device_get_name.argtypes = [_p]
_lib.ei_seat_bind_capabilities.restype = None  # variádica com sentinela NULL
_lib.ei_event_pointer_get_dx.restype = ctypes.c_double
_lib.ei_event_pointer_get_dx.argtypes = [_p]
_lib.ei_event_pointer_get_dy.restype = ctypes.c_double
_lib.ei_event_pointer_get_dy.argtypes = [_p]
_lib.ei_event_button_get_button.restype = ctypes.c_uint32
_lib.ei_event_button_get_button.argtypes = [_p]
_lib.ei_event_button_get_is_press.restype = ctypes.c_bool
_lib.ei_event_button_get_is_press.argtypes = [_p]
_lib.ei_event_scroll_get_dx.restype = ctypes.c_double
_lib.ei_event_scroll_get_dx.argtypes = [_p]
_lib.ei_event_scroll_get_dy.restype = ctypes.c_double
_lib.ei_event_scroll_get_dy.argtypes = [_p]
_lib.ei_event_scroll_get_discrete_dx.restype = ctypes.c_int32
_lib.ei_event_scroll_get_discrete_dx.argtypes = [_p]
_lib.ei_event_scroll_get_discrete_dy.restype = ctypes.c_int32
_lib.ei_event_scroll_get_discrete_dy.argtypes = [_p]
_lib.ei_event_keyboard_get_key.restype = ctypes.c_uint32
_lib.ei_event_keyboard_get_key.argtypes = [_p]
_lib.ei_event_keyboard_get_key_is_press.restype = ctypes.c_bool
_lib.ei_event_keyboard_get_key_is_press.argtypes = [_p]

# enum ei_event_type (libei 1.x)
EV_CONNECT, EV_DISCONNECT, EV_SEAT_ADDED, EV_SEAT_REMOVED = 1, 2, 3, 4
EV_DEVICE_ADDED, EV_DEVICE_REMOVED, EV_DEVICE_PAUSED, EV_DEVICE_RESUMED = 5, 6, 7, 8
EV_FRAME = 100
EV_START_EMULATING, EV_STOP_EMULATING = 200, 201
EV_POINTER_MOTION = 300
EV_BUTTON = 500
EV_SCROLL_DELTA, EV_SCROLL_STOP, EV_SCROLL_CANCEL, EV_SCROLL_DISCRETE = 600, 601, 602, 603
EV_KEYBOARD_KEY = 700

CAP_POINTER, CAP_POINTER_ABS, CAP_KEYBOARD, CAP_TOUCH, CAP_SCROLL, CAP_BUTTON = 1, 2, 4, 8, 16, 32


@dataclass
class Motion:
    dx: float
    dy: float


@dataclass
class Button:
    button: int
    pressed: bool


@dataclass
class Scroll:
    dx: float          # pixels (delta) ou 120-avos (discrete)
    dy: float
    discrete: bool


@dataclass
class Key:
    key: int           # keycode evdev
    pressed: bool


class EiReceiver:
    def __init__(self, fd: int, name: str = "mwbd"):
        self.ei = _lib.ei_new_receiver(None)
        if not self.ei:
            raise RuntimeError("ei_new_receiver falhou")
        _lib.ei_configure_name(self.ei, name.encode())
        rc = _lib.ei_setup_backend_fd(self.ei, fd)
        if rc != 0:
            raise RuntimeError(f"ei_setup_backend_fd rc={rc}")
        self.connected = False
        self.emulating = False

    def fileno(self) -> int:
        return _lib.ei_get_fd(self.ei)

    def pump(self) -> list:
        """Despacha o socket e devolve os eventos de entrada (Motion/Button/Scroll/Key)."""
        _lib.ei_dispatch(self.ei)
        out = []
        while True:
            ev = _lib.ei_get_event(self.ei)
            if not ev:
                break
            t = _lib.ei_event_get_type(ev)
            if t == EV_CONNECT:
                self.connected = True
            elif t == EV_DISCONNECT:
                self.connected = False
            elif t == EV_SEAT_ADDED:
                seat = _lib.ei_event_get_seat(ev)
                # variádica: o 1º arg precisa ir como ponteiro de 64 bits e o terminador como NULL
                _lib.ei_seat_bind_capabilities(
                    ctypes.c_void_p(seat), ctypes.c_int(CAP_POINTER), ctypes.c_int(CAP_KEYBOARD),
                    ctypes.c_int(CAP_BUTTON), ctypes.c_int(CAP_SCROLL), ctypes.c_void_p(None))
            elif t == EV_START_EMULATING:
                self.emulating = True
            elif t == EV_STOP_EMULATING:
                self.emulating = False
            elif t == EV_POINTER_MOTION:
                out.append(Motion(_lib.ei_event_pointer_get_dx(ev), _lib.ei_event_pointer_get_dy(ev)))
            elif t == EV_BUTTON:
                out.append(Button(_lib.ei_event_button_get_button(ev), _lib.ei_event_button_get_is_press(ev)))
            elif t == EV_SCROLL_DISCRETE:
                out.append(Scroll(_lib.ei_event_scroll_get_discrete_dx(ev), _lib.ei_event_scroll_get_discrete_dy(ev), True))
            elif t == EV_SCROLL_DELTA:
                out.append(Scroll(_lib.ei_event_scroll_get_dx(ev), _lib.ei_event_scroll_get_dy(ev), False))
            elif t == EV_KEYBOARD_KEY:
                out.append(Key(_lib.ei_event_keyboard_get_key(ev), _lib.ei_event_keyboard_get_key_is_press(ev)))
            _lib.ei_event_unref(ev)
        return out
