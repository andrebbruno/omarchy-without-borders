"""libei *sender* (ctypes): inject pointer/keyboard events through an EIS socket handed out by
the XDG RemoteDesktop portal (GNOME, KDE). Counterpart of ei_receiver.py."""
from __future__ import annotations

import ctypes
import logging

from .ei_receiver import (
    CAP_BUTTON, CAP_KEYBOARD, CAP_POINTER, CAP_POINTER_ABS, CAP_SCROLL,
    EV_CONNECT, EV_DEVICE_ADDED, EV_DEVICE_PAUSED, EV_DEVICE_REMOVED, EV_DEVICE_RESUMED, EV_DISCONNECT,
    EV_SEAT_ADDED, _lib,
)

log = logging.getLogger("ei_sender")
_p = ctypes.c_void_p

_lib.ei_new_sender.restype = _p
_lib.ei_new_sender.argtypes = [_p]
_lib.ei_now.restype = ctypes.c_uint64
_lib.ei_now.argtypes = [_p]
_lib.ei_device_has_capability.restype = ctypes.c_bool
_lib.ei_device_has_capability.argtypes = [_p, ctypes.c_int]
_lib.ei_device_ref.restype = _p
_lib.ei_device_ref.argtypes = [_p]
_lib.ei_device_unref.restype = _p
_lib.ei_device_unref.argtypes = [_p]
_lib.ei_device_get_region.restype = _p
_lib.ei_device_get_region.argtypes = [_p, ctypes.c_size_t]
for _n in ("x", "y", "width", "height"):
    getattr(_lib, f"ei_region_get_{_n}").restype = ctypes.c_uint32
    getattr(_lib, f"ei_region_get_{_n}").argtypes = [_p]
_lib.ei_device_start_emulating.argtypes = [_p, ctypes.c_uint32]
_lib.ei_device_stop_emulating.argtypes = [_p]
_lib.ei_device_frame.argtypes = [_p, ctypes.c_uint64]
_lib.ei_device_pointer_motion.argtypes = [_p, ctypes.c_double, ctypes.c_double]
_lib.ei_device_pointer_motion_absolute.argtypes = [_p, ctypes.c_double, ctypes.c_double]
_lib.ei_device_button_button.argtypes = [_p, ctypes.c_uint32, ctypes.c_bool]
_lib.ei_device_scroll_discrete.argtypes = [_p, ctypes.c_int32, ctypes.c_int32]
_lib.ei_device_keyboard_key.argtypes = [_p, ctypes.c_uint32, ctypes.c_bool]


class _Dev:
    def __init__(self, ptr, caps: int, regions):
        self.ptr = _lib.ei_device_ref(ptr)
        self.caps = caps
        self.regions = regions      # [(x, y, w, h)]
        self.resumed = False
        self.emulating = False
        self.seq = 0


class EiSender:
    """Sender context on an EIS fd. Call pump() whenever fileno() is readable; devices become
    usable after the compositor resumes them (a few ms after connecting)."""

    def __init__(self, fd: int, name: str = "owb"):
        self.ei = _lib.ei_new_sender(None)
        if not self.ei:
            raise RuntimeError("ei_new_sender failed")
        _lib.ei_configure_name(self.ei, name.encode())
        rc = _lib.ei_setup_backend_fd(self.ei, fd)
        if rc != 0:
            raise RuntimeError(f"ei_setup_backend_fd rc={rc}")
        self.connected = False
        self.devices: dict[int, _Dev] = {}
        self._pressed: set[int] = set()

    def fileno(self) -> int:
        return _lib.ei_get_fd(self.ei)

    # ------------------------------------------------------------ event pump
    def pump(self):
        _lib.ei_dispatch(self.ei)
        while True:
            ev = _lib.ei_get_event(self.ei)
            if not ev:
                break
            t = _lib.ei_event_get_type(ev)
            if t == EV_CONNECT:
                self.connected = True
                log.info("EIS sender connected")
            elif t == EV_DISCONNECT:
                self.connected = False
                self.devices.clear()
                log.warning("EIS sender disconnected")
            elif t == EV_SEAT_ADDED:
                seat = _lib.ei_event_get_seat(ev)
                _lib.ei_seat_bind_capabilities(
                    ctypes.c_void_p(seat), ctypes.c_int(CAP_POINTER), ctypes.c_int(CAP_POINTER_ABS),
                    ctypes.c_int(CAP_KEYBOARD), ctypes.c_int(CAP_BUTTON), ctypes.c_int(CAP_SCROLL),
                    ctypes.c_void_p(None))
            elif t == EV_DEVICE_ADDED:
                dev = _lib.ei_event_get_device(ev)
                caps = sum(c for c in (CAP_POINTER, CAP_POINTER_ABS, CAP_KEYBOARD, CAP_BUTTON, CAP_SCROLL)
                           if _lib.ei_device_has_capability(dev, c))
                regions = []
                i = 0
                while True:
                    r = _lib.ei_device_get_region(dev, i)
                    if not r:
                        break
                    regions.append((_lib.ei_region_get_x(r), _lib.ei_region_get_y(r),
                                    _lib.ei_region_get_width(r), _lib.ei_region_get_height(r)))
                    i += 1
                self.devices[dev] = _Dev(dev, caps, regions)
                name = _lib.ei_device_get_name(dev) or b"?"
                log.info("EIS device %s caps=0x%x regions=%s", name.decode(errors="replace"), caps, regions)
            elif t == EV_DEVICE_REMOVED:
                d = self.devices.pop(_lib.ei_event_get_device(ev), None)
                if d:
                    _lib.ei_device_unref(d.ptr)
            elif t == EV_DEVICE_RESUMED:
                d = self.devices.get(_lib.ei_event_get_device(ev))
                if d:
                    d.resumed = True
            elif t == EV_DEVICE_PAUSED:
                d = self.devices.get(_lib.ei_event_get_device(ev))
                if d:
                    d.resumed = d.emulating = False
            _lib.ei_event_unref(ev)

    # ------------------------------------------------------------ helpers
    def _dev(self, cap: int) -> _Dev | None:
        for d in self.devices.values():
            if d.caps & cap and d.resumed:
                if not d.emulating:
                    d.seq += 1
                    _lib.ei_device_start_emulating(d.ptr, d.seq)
                    d.emulating = True
                return d
        return None

    def _frame(self, d: _Dev):
        _lib.ei_device_frame(d.ptr, _lib.ei_now(self.ei))

    def desktop_bounds(self) -> tuple[int, int, int, int]:
        """Bounding box of all absolute-pointer regions (x, y, w, h)."""
        regs = [r for d in self.devices.values() for r in d.regions]
        if not regs:
            return (0, 0, 0, 0)
        x0 = min(r[0] for r in regs)
        y0 = min(r[1] for r in regs)
        x1 = max(r[0] + r[2] for r in regs)
        y1 = max(r[1] + r[3] for r in regs)
        return (x0, y0, x1 - x0, y1 - y0)

    # ------------------------------------------------------------ injection
    def motion_abs(self, x: float, y: float) -> bool:
        """Absolute position in desktop coordinates."""
        for d in self.devices.values():
            if d.caps & CAP_POINTER_ABS and d.resumed:
                for rx, ry, rw, rh in d.regions:
                    if rx <= x < rx + rw and ry <= y < ry + rh:
                        self._dev(CAP_POINTER_ABS)
                        if not d.emulating:
                            d.seq += 1
                            _lib.ei_device_start_emulating(d.ptr, d.seq)
                            d.emulating = True
                        _lib.ei_device_pointer_motion_absolute(d.ptr, x, y)
                        self._frame(d)
                        return True
        d = self._dev(CAP_POINTER_ABS)
        if d:   # outside every region: clamp into the first one
            rx, ry, rw, rh = d.regions[0] if d.regions else (0, 0, 1, 1)
            _lib.ei_device_pointer_motion_absolute(d.ptr, min(max(x, rx), rx + rw - 1), min(max(y, ry), ry + rh - 1))
            self._frame(d)
            return True
        return False

    def motion_rel(self, dx: float, dy: float):
        d = self._dev(CAP_POINTER)
        if d:
            _lib.ei_device_pointer_motion(d.ptr, dx, dy)
            self._frame(d)

    def button(self, button: int, pressed: bool):
        d = self._dev(CAP_BUTTON)
        if d:
            _lib.ei_device_button_button(d.ptr, button, pressed)
            self._frame(d)

    def scroll_discrete(self, dx120: int, dy120: int):
        """In 1/120 notch units; positive = down / right."""
        d = self._dev(CAP_SCROLL)
        if d:
            _lib.ei_device_scroll_discrete(d.ptr, dx120, dy120)
            self._frame(d)

    def key(self, keycode: int, pressed: bool):
        d = self._dev(CAP_KEYBOARD)
        if d:
            if pressed:
                self._pressed.add(keycode)
            else:
                self._pressed.discard(keycode)
            _lib.ei_device_keyboard_key(d.ptr, keycode, pressed)
            self._frame(d)

    def release_all(self):
        for kc in list(self._pressed):
            self.key(kc, False)
        self._pressed.clear()
