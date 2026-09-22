"""XDG desktop portal backend (GNOME, KDE, any compositor with the portals):

- org.freedesktop.portal.RemoteDesktop  → inject input (libei sender on ConnectToEIS)
- org.freedesktop.portal.InputCapture   → screen-edge barriers + EIS receiver

Uses PyGObject (Gio) for DBus; a GLib main loop runs in a helper thread and hands portal
signals to the daemon through `post(callable)`.
"""
from __future__ import annotations

import logging
import os
import threading
import time

import gi

gi.require_version("Gio", "2.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gio, GLib  # noqa: E402

log = logging.getLogger("portal")

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
IFACE_RD = "org.freedesktop.portal.RemoteDesktop"
IFACE_IC = "org.freedesktop.portal.InputCapture"
IFACE_REQ = "org.freedesktop.portal.Request"
IFACE_SESSION = "org.freedesktop.portal.Session"

RD_KEYBOARD, RD_POINTER = 1, 2
IC_KEYBOARD, IC_POINTER = 1, 2
BARRIER_ID = {"left": 1, "right": 2, "top": 3, "bottom": 4}


class PortalError(RuntimeError):
    pass


class Portal:
    """One DBus connection + GLib loop shared by both portal sessions."""

    def __init__(self, post):
        self.post = post                      # run a callable on the daemon's main thread
        self.bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.sender = self.bus.get_unique_name()[1:].replace(".", "_")
        self.loop = GLib.MainLoop()
        threading.Thread(target=self.loop.run, name="glib", daemon=True).start()
        self._n = 0

    # ---- generic portal request/response dance --------------------------------------
    def request(self, iface: str, method: str, sig: str, *args, opts_index: int = -1, timeout: float = 120.0) -> dict:
        """Call a portal method that returns a Request object and wait for its Response signal.
        args[opts_index] must be the options dict (str -> GLib.Variant); handle_token is added."""
        self._n += 1
        token = f"owb{os.getpid()}_{self._n}"
        req_path = f"{PATH}/request/{self.sender}/{token}"
        done = threading.Event()
        result: dict = {}

        def on_response(conn, sender, path, iface_, signal, params_):
            code, out = params_.unpack()
            result["code"], result["out"] = code, out
            done.set()

        sub = self.bus.signal_subscribe(BUS, IFACE_REQ, "Response", req_path, None,
                                        Gio.DBusSignalFlags.NONE, on_response)
        args = list(args)
        opts = dict(args[opts_index])
        opts["handle_token"] = GLib.Variant("s", token)
        args[opts_index] = opts
        log.debug("%s.%s -> waiting for %s", iface, method, req_path)
        try:
            self.bus.call_sync(BUS, PATH, iface, method, GLib.Variant(sig, tuple(args)), None,
                               Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error as e:
            self.bus.signal_unsubscribe(sub)
            raise PortalError(f"{iface}.{method}: {e.message}") from e
        if not done.wait(timeout):
            self.bus.signal_unsubscribe(sub)
            raise PortalError(f"{iface}.{method}: no response")
        self.bus.signal_unsubscribe(sub)
        if result["code"] != 0:
            raise PortalError(f"{iface}.{method}: response {result['code']} (cancelled/denied)")
        return result["out"] or {}

    def call(self, iface: str, method: str, params: GLib.Variant):
        try:
            return self.bus.call_sync(BUS, PATH, iface, method, params, None, Gio.DBusCallFlags.NONE, -1, None)
        except GLib.Error as e:
            raise PortalError(f"{iface}.{method}: {e.message}") from e

    def call_fd(self, iface: str, method: str, params: GLib.Variant) -> int:
        try:
            _, fdlist = self.bus.call_with_unix_fd_list_sync(BUS, PATH, iface, method, params, None,
                                                             Gio.DBusCallFlags.NONE, -1, None, None)
        except GLib.Error as e:
            raise PortalError(f"{iface}.{method}: {e.message}") from e
        return fdlist.get(0)

    def subscribe(self, iface: str, signal: str, cb):
        return self.bus.signal_subscribe(BUS, iface, signal, PATH, None, Gio.DBusSignalFlags.NONE,
                                         lambda c, s, p, i, sig, params: cb(*params.unpack()))

    def session_token(self) -> str:
        self._n += 1
        return f"owb{os.getpid()}_s{self._n}"


def _variant(sig: str, items) -> GLib.Variant:
    return GLib.Variant(sig, tuple(items))


# ============================================================================ RemoteDesktop
class RemoteDesktop:
    """Injection session. The first run shows the portal's consent dialog; the restore token
    (persist_mode=2) makes later starts silent."""

    def __init__(self, portal: Portal, restore_token: str | None, on_token):
        self.p = portal
        tok = portal.session_token()
        out = portal.request(IFACE_RD, "CreateSession", "(a{sv})", {"session_handle_token": GLib.Variant("s", tok)})
        self.session = out["session_handle"]
        opts = {"types": GLib.Variant("u", RD_KEYBOARD | RD_POINTER), "persist_mode": GLib.Variant("u", 2)}
        if restore_token:
            opts["restore_token"] = GLib.Variant("s", restore_token)
        portal.request(IFACE_RD, "SelectDevices", "(oa{sv})", self.session, opts)
        log.info("RemoteDesktop: starting session (a consent dialog may appear the first time)")
        out = portal.request(IFACE_RD, "Start", "(osa{sv})", self.session, "", {})
        if out.get("restore_token"):
            on_token(out["restore_token"])
        self.fd = portal.call_fd(IFACE_RD, "ConnectToEIS", _variant("(oa{sv})", [self.session, {}]))
        log.info("RemoteDesktop: EIS fd %d", self.fd)

    def close(self):
        try:
            self.p.bus.call_sync(BUS, self.session, IFACE_SESSION, "Close", None, None, Gio.DBusCallFlags.NONE, 2000, None)
        except GLib.Error:
            pass


class PortalInjector:
    """Same interface as WaylandInjector, backed by RemoteDesktop + libei sender."""

    def __init__(self, portal: Portal, restore_token: str | None, on_token):
        from .ei_sender import EiSender
        self.rd = RemoteDesktop(portal, restore_token, on_token)
        self.ei = EiSender(self.rd.fd)
        self.capture_mgr = None   # no Hyprland manager here
        # let the compositor announce devices/regions
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and not self.ei.desktop_bounds()[2]:
            import select
            r, _, _ = select.select([self.ei.fileno()], [], [], 0.2)
            if r:
                self.ei.pump()
        self.ei.pump()
        log.info("portal injector ready, desktop %s", self.ei.desktop_bounds())

    def move_abs(self, x: int, y: int, extent: int = 65535):
        bx, by, bw, bh = self.ei.desktop_bounds()
        if not bw:
            return
        self.ei.motion_abs(bx + max(0, min(extent, x)) * (bw - 1) / extent,
                           by + max(0, min(extent, y)) * (bh - 1) / extent)

    def move_rel(self, dx: int, dy: int):
        self.ei.motion_rel(float(dx), float(dy))

    def button(self, btn: int, pressed: bool):
        self.ei.button(btn, pressed)

    def wheel(self, delta: int, horizontal: bool = False):
        # Windows: +120 per notch, positive = up/left; EIS: positive = down/right
        self.ei.scroll_discrete(delta if horizontal else 0, 0 if horizontal else -delta)

    def key(self, keycode: int, pressed: bool):
        self.ei.key(keycode, pressed)

    def release_all(self):
        self.ei.release_all()

    def flush(self):
        pass

    def fileno(self) -> int:
        return self.ei.fileno()

    def dispatch_pending(self):
        self.ei.pump()

    def close(self):
        self.release_all()
        self.rd.close()


# ============================================================================ InputCapture
class PortalCapture:
    """Same interface as capture.InputCapture: set_edges(), release(), edges, geom, enabled."""

    def __init__(self, portal: Portal, on_eis_fd, on_activated, on_deactivated):
        self.p = portal
        self._on_activated = on_activated
        self._on_deactivated = on_deactivated
        self.edges: set[str] = set()
        self.geom = (0, 0, 0, 0)
        self.enabled = False
        self.zone_set = 0
        self.zones: list[tuple[int, int, int, int]] = []
        tok = portal.session_token()
        out = portal.request(IFACE_IC, "CreateSession", "(sa{sv})", "", {
            "session_handle_token": GLib.Variant("s", tok),
            "capabilities": GLib.Variant("u", IC_KEYBOARD | IC_POINTER)})
        self.session = out["session_handle"]
        self._read_zones()
        portal.subscribe(IFACE_IC, "Activated", self._activated)
        portal.subscribe(IFACE_IC, "Deactivated", self._deactivated)
        portal.subscribe(IFACE_IC, "ZonesChanged", self._zones_changed)
        portal.subscribe(IFACE_IC, "Disabled", lambda s, o: log.info("InputCapture disabled by the compositor"))
        fd = portal.call_fd(IFACE_IC, "ConnectToEIS", _variant("(oa{sv})", [self.session, {}]))
        on_eis_fd(fd)

    def _read_zones(self):
        out = self.p.request(IFACE_IC, "GetZones", "(oa{sv})", self.session, {})
        self.zone_set = out["zone_set"]
        self.zones = [(x, y, w, h) for (w, h, x, y) in out["zones"]]
        # geometry = the zone at the origin (primary), else the first one
        z = next((z for z in self.zones if z[0] == 0 and z[1] == 0), self.zones[0] if self.zones else (0, 0, 0, 0))
        self.geom = z
        log.info("InputCapture zones %s (set %d)", self.zones, self.zone_set)

    def _activated(self, session, opts):
        if session != self.session:
            return
        aid = opts.get("activation_id", 0)
        x, y = opts.get("cursor_position", (0.0, 0.0))
        bid = opts.get("barrier_id", 0)
        edge = next((e for e, i in BARRIER_ID.items() if i == bid), "?")
        self.p.post(lambda: self._on_activated(aid, float(x), float(y), edge))

    def _deactivated(self, session, opts):
        if session == self.session:
            aid = opts.get("activation_id", 0)
            self.p.post(lambda: self._on_deactivated(aid))

    def _zones_changed(self, session, opts):
        if session == self.session:
            self.p.post(self._rezone)

    def _rezone(self):
        self._read_zones()
        edges, self.edges = self.edges, set()
        self.enabled = False
        self.set_edges(edges)

    def set_edges(self, edges: set[str]):
        if edges == self.edges and (self.enabled or not edges):
            return
        log.debug("set_edges %s (was %s, enabled=%s)", sorted(edges), sorted(self.edges), self.enabled)
        if self.enabled:
            try:
                self.p.call(IFACE_IC, "Disable", _variant("(oa{sv})", [self.session, {}]))
            except PortalError as e:
                log.debug("Disable: %s", e)
            self.enabled = False
        self.edges = set(edges)
        if not edges:
            log.info("no connected neighbours — capture off")
            return
        x, y, w, h = self.geom
        lines = {
            "left": (x, y, x, y + h - 1),
            "right": (x + w, y, x + w, y + h - 1),
            "top": (x, y, x + w - 1, y),
            "bottom": (x, y + h, x + w - 1, y + h),
        }
        barriers = [{"barrier_id": GLib.Variant("u", BARRIER_ID[e]),
                     "position": GLib.Variant("(iiii)", lines[e])} for e in edges]
        out = self.p.request(IFACE_IC, "SetPointerBarriers", "(oa{sv}aa{sv}u)", self.session, {}, barriers,
                             self.zone_set, opts_index=1)
        failed = out.get("failed_barriers", [])
        if failed:
            log.warning("barriers rejected by the portal: %s", failed)
        self.p.call(IFACE_IC, "Enable", _variant("(oa{sv})", [self.session, {}]))   # plain method, no Request
        self.enabled = True
        log.info("capture active on edges %s (zone %dx%d)", sorted(edges), w, h)

    def release(self, activation_id: int, x: float, y: float):
        try:
            self.p.call(IFACE_IC, "Release", _variant("(oa{sv})", [self.session, {
                "activation_id": GLib.Variant("u", activation_id),
                "cursor_position": GLib.Variant("(dd)", (float(x), float(y)))}]))
        except PortalError as e:
            log.warning("Release: %s", e)
