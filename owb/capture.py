"""Captura de entrada via hyprland_input_capture_v1 (barreiras nas bordas + socket EIS)."""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys

from .wl.hyprland_input_capture_v1 import HyprlandInputCaptureManagerV1

log = logging.getLogger("capture")

EDGES = ("left", "right", "top", "bottom")
BARRIER_ID = {"left": 1, "right": 2, "top": 3, "bottom": 4}


def monitor_geometry() -> tuple[int, int, int, int]:
    """(x, y, largura, altura) lógicos do monitor focado (hyprctl)."""
    out = subprocess.run(["hyprctl", "-j", "monitors"], capture_output=True, text=True, check=True).stdout
    mons = json.loads(out)
    m = next((m for m in mons if m.get("focused")), mons[0])
    scale = float(m.get("scale") or 1.0)
    return int(m["x"]), int(m["y"]), int(round(m["width"] / scale)), int(round(m["height"] / scale))


class InputCapture:
    """Uma sessão de captura. Callbacks: on_eis_fd(fd), on_activated(id, x, y, edge), on_deactivated(id)."""

    def __init__(self, manager: HyprlandInputCaptureManagerV1, on_eis_fd, on_activated, on_deactivated):
        self.session = manager.create_session("mwbd")
        self.session.dispatcher["eis_fd"] = lambda s, fd: on_eis_fd(fd)
        self.session.dispatcher["activated"] = self._activated
        self.session.dispatcher["deactivated"] = lambda s, aid: on_deactivated(aid)
        self.session.dispatcher["disabled"] = lambda s: log.info("sessão de captura desabilitada pelo compositor")
        self._on_activated = on_activated
        self.edges: set[str] = set()
        self.geom = (0, 0, 0, 0)
        self.enabled = False

    def _activated(self, s, activation_id, x, y, barrier_id):
        edge = next((e for e, i in BARRIER_ID.items() if i == barrier_id), "?")
        self._on_activated(activation_id, float(x), float(y), edge)

    def set_edges(self, edges: set[str]):
        """(Re)define as barreiras: uma por borda que tem vizinho conectado."""
        if edges == self.edges and (self.enabled or not edges):
            return
        if self.enabled:
            self.session.disable()
            self.enabled = False
        self.session.clear_barriers()
        self.edges = set(edges)
        if not edges:
            log.info("sem vizinhos conectados — captura desligada")
            return
        x, y, w, h = monitor_geometry()
        self.geom = (x, y, w, h)
        # barreiras cobrem a borda inteira, de canto a canto
        # Hyprland (InputCapture.cpp): segmento inclusivo de y..y+h-1; borda direita em x+w, inferior em y+h
        lines = {
            "left": (x, y, x, y + h - 1),
            "right": (x + w, y, x + w, y + h - 1),
            "top": (x, y, x + w - 1, y),
            "bottom": (x, y + h, x + w - 1, y + h),
        }
        for e in edges:
            x1, y1, x2, y2 = lines[e]
            self.session.add_barrier(1, BARRIER_ID[e], x1, y1, x2, y2)
        self.session.enable()
        self.enabled = True
        log.info("captura ativa nas bordas %s (tela %dx%d)", sorted(edges), w, h)

    def release(self, activation_id: int, x: float, y: float):
        self.session.release(activation_id, x, y)
