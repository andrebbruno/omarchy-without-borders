#!/bin/sh
# Regenera os bindings pywayland em owb/wl a partir dos XML (rode após atualizar os protocolos).
cd "$(dirname "$0")/../owb/wl" && python -m pywayland.scanner -i /usr/share/wayland/wayland.xml \
  wlr-virtual-pointer-unstable-v1.xml virtual-keyboard-unstable-v1.xml hyprland-input-capture-v1.xml -o .
