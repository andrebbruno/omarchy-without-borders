"""Tabela Windows Virtual-Key -> keycode evdev (linux/input-event-codes.h).

O MWB envia wVk + flag EXTENDED. Mapeamos pela posição física da tecla (layout US
como referência, que é como o Windows atribui VK_OEM_*); o xkb do lado Linux
(layout br) decide o caractere. Teclas ABNT2 (VK_ABNT_C1/C2) incluídas.
"""

# nomes evdev usados abaixo
KEY = dict(
    ESC=1, N1=2, N2=3, N3=4, N4=5, N5=6, N6=7, N7=8, N8=9, N9=10, N0=11, MINUS=12, EQUAL=13,
    BACKSPACE=14, TAB=15, Q=16, W=17, E=18, R=19, T=20, Y=21, U=22, I=23, O=24, P=25,
    LEFTBRACE=26, RIGHTBRACE=27, ENTER=28, LEFTCTRL=29, A=30, S=31, D=32, F=33, G=34, H=35,
    J=36, K=37, L=38, SEMICOLON=39, APOSTROPHE=40, GRAVE=41, LEFTSHIFT=42, BACKSLASH=43,
    Z=44, X=45, C=46, V=47, B=48, N=49, M=50, COMMA=51, DOT=52, SLASH=53, RIGHTSHIFT=54,
    KPASTERISK=55, LEFTALT=56, SPACE=57, CAPSLOCK=58, F1=59, F2=60, F3=61, F4=62, F5=63,
    F6=64, F7=65, F8=66, F9=67, F10=68, NUMLOCK=69, SCROLLLOCK=70, KP7=71, KP8=72, KP9=73,
    KPMINUS=74, KP4=75, KP5=76, KP6=77, KPPLUS=78, KP1=79, KP2=80, KP3=81, KP0=82, KPDOT=83,
    K102ND=86, F11=87, F12=88, RO=89, KPENTER=96, RIGHTCTRL=97, KPSLASH=98, SYSRQ=99,
    RIGHTALT=100, HOME=102, UP=103, PAGEUP=104, LEFT=105, RIGHT=106, END=107, DOWN=108,
    PAGEDOWN=109, INSERT=110, DELETE=111, MUTE=113, VOLUMEDOWN=114, VOLUMEUP=115,
    PAUSE=119, KPCOMMA=121, LEFTMETA=125, RIGHTMETA=126, COMPOSE=127, MAIL=155, BACK=158,
    FORWARD=159, NEXTSONG=163, PLAYPAUSE=164, PREVIOUSSONG=165, STOPCD=166, HOMEPAGE=172,
    REFRESH=173, F13=183, F14=184, F15=185, F16=186, F17=187, F18=188, F19=189, F20=190,
    F21=191, F22=192, F23=193, F24=194, SEARCH=217, CALC=140, SLEEP=142,
)

VK_TO_KEY = {
    0x08: KEY["BACKSPACE"], 0x09: KEY["TAB"], 0x0D: KEY["ENTER"], 0x13: KEY["PAUSE"],
    0x14: KEY["CAPSLOCK"], 0x1B: KEY["ESC"], 0x20: KEY["SPACE"],
    0x21: KEY["PAGEUP"], 0x22: KEY["PAGEDOWN"], 0x23: KEY["END"], 0x24: KEY["HOME"],
    0x25: KEY["LEFT"], 0x26: KEY["UP"], 0x27: KEY["RIGHT"], 0x28: KEY["DOWN"],
    0x2C: KEY["SYSRQ"], 0x2D: KEY["INSERT"], 0x2E: KEY["DELETE"],
    0x5B: KEY["LEFTMETA"], 0x5C: KEY["RIGHTMETA"], 0x5D: KEY["COMPOSE"], 0x5F: KEY["SLEEP"],
    0x6A: KEY["KPASTERISK"], 0x6B: KEY["KPPLUS"], 0x6D: KEY["KPMINUS"], 0x6E: KEY["KPDOT"],
    0x6F: KEY["KPSLASH"], 0x90: KEY["NUMLOCK"], 0x91: KEY["SCROLLLOCK"],
    # modificadores (o hook LL entrega os VKs L/R específicos)
    0x10: KEY["LEFTSHIFT"], 0xA0: KEY["LEFTSHIFT"], 0xA1: KEY["RIGHTSHIFT"],
    0x11: KEY["LEFTCTRL"], 0xA2: KEY["LEFTCTRL"], 0xA3: KEY["RIGHTCTRL"],
    0x12: KEY["LEFTALT"], 0xA4: KEY["LEFTALT"], 0xA5: KEY["RIGHTALT"],
    # navegador / mídia
    0xA6: KEY["BACK"], 0xA7: KEY["FORWARD"], 0xA8: KEY["REFRESH"], 0xAA: KEY["SEARCH"],
    0xAC: KEY["HOMEPAGE"], 0xAD: KEY["MUTE"], 0xAE: KEY["VOLUMEDOWN"], 0xAF: KEY["VOLUMEUP"],
    0xB0: KEY["NEXTSONG"], 0xB1: KEY["PREVIOUSSONG"], 0xB2: KEY["STOPCD"], 0xB3: KEY["PLAYPAUSE"],
    0xB4: KEY["MAIL"], 0xB7: KEY["CALC"],
    # OEM (posições do layout US)
    0xBA: KEY["SEMICOLON"], 0xBB: KEY["EQUAL"], 0xBC: KEY["COMMA"], 0xBD: KEY["MINUS"],
    0xBE: KEY["DOT"], 0xBF: KEY["SLASH"], 0xC0: KEY["GRAVE"], 0xDB: KEY["LEFTBRACE"],
    0xDC: KEY["BACKSLASH"], 0xDD: KEY["RIGHTBRACE"], 0xDE: KEY["APOSTROPHE"], 0xE2: KEY["K102ND"],
    # ABNT2
    0xC1: KEY["RO"], 0xC2: KEY["KPCOMMA"],
}
# dígitos 0-9 e letras A-Z
for i, kc in enumerate([KEY["N0"], KEY["N1"], KEY["N2"], KEY["N3"], KEY["N4"], KEY["N5"], KEY["N6"], KEY["N7"], KEY["N8"], KEY["N9"]]):
    VK_TO_KEY[0x30 + i] = kc
for i, name in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    VK_TO_KEY[0x41 + i] = KEY[name]
# numpad 0-9
for i, kc in enumerate([KEY["KP0"], KEY["KP1"], KEY["KP2"], KEY["KP3"], KEY["KP4"], KEY["KP5"], KEY["KP6"], KEY["KP7"], KEY["KP8"], KEY["KP9"]]):
    VK_TO_KEY[0x60 + i] = kc
# F1-F24
for i in range(24):
    VK_TO_KEY[0x70 + i] = KEY[f"F{i + 1}"]


def vk_to_keycode(vk: int, extended: bool) -> int | None:
    """Alguns VKs mudam de tecla física com a flag EXTENDED (numpad x navegação)."""
    if extended:
        if vk == 0x0D:
            return KEY["KPENTER"]
        if vk == 0x11:
            return KEY["RIGHTCTRL"]
        if vk == 0x12:
            return KEY["RIGHTALT"]
    else:
        # sem EXTENDED, as teclas de navegação vêm do teclado numérico (NumLock off)
        nav_to_kp = {0x2D: KEY["KP0"], 0x23: KEY["KP1"], 0x28: KEY["KP2"], 0x22: KEY["KP3"],
                     0x25: KEY["KP4"], 0x0C: KEY["KP5"], 0x27: KEY["KP6"], 0x24: KEY["KP7"],
                     0x26: KEY["KP8"], 0x21: KEY["KP9"], 0x2E: KEY["KPDOT"]}
        if vk in nav_to_kp:
            return nav_to_kp[vk]
    return VK_TO_KEY.get(vk)


# ---- sentido inverso (Linux como host): keycode evdev -> (VK, extended) ----
# Teclas que o Windows espera com KEYEVENTF_EXTENDEDKEY (scancode E0).
_EXTENDED = {KEY[n] for n in ("RIGHTCTRL", "RIGHTALT", "INSERT", "DELETE", "HOME", "END", "PAGEUP",
                              "PAGEDOWN", "UP", "DOWN", "LEFT", "RIGHT", "NUMLOCK", "KPENTER",
                              "KPSLASH", "SYSRQ", "LEFTMETA", "RIGHTMETA", "COMPOSE", "PAUSE")}
KEY_TO_VK: dict[int, int] = {}
for _vk, _kc in VK_TO_KEY.items():
    # preferir VKs específicos L/R (0xA0..0xA5) aos genéricos SHIFT/CONTROL/MENU
    if _kc not in KEY_TO_VK or _vk >= 0xA0:
        KEY_TO_VK[_kc] = _vk
KEY_TO_VK[KEY["KPENTER"]] = 0x0D
KEY_TO_VK[KEY["RIGHTCTRL"]] = 0xA3
KEY_TO_VK[KEY["RIGHTALT"]] = 0xA5


def keycode_to_vk(kc: int) -> tuple[int, bool] | None:
    vk = KEY_TO_VK.get(kc)
    if vk is None:
        return None
    return vk, kc in _EXTENDED


# ---- importação de um layout exportado do Windows (scripts/export-windows-keymap.ps1) ----
# scancode set 1 -> keycode evdev (tabela atkbd do kernel); iguais até 0x58, fora estes:
_ATKBD_SPECIAL = {0x73: KEY["RO"], 0x7E: KEY["KPCOMMA"], 0x5B: KEY["LEFTMETA"], 0x5C: KEY["RIGHTMETA"],
                  0x5D: KEY["COMPOSE"], 0x5F: KEY["SLEEP"], 0x70: 93, 0x79: 92, 0x7B: 94, 0x7D: 124}


def overrides_from_windows_keymap(text: str) -> dict[str, int]:
    """Lê linhas 'vk,scancode' e devolve só os VKs cujo keycode difere da tabela embutida."""
    out: dict[str, int] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "," not in line:
            continue
        vk, sc = (int(x) for x in line.split(",", 1))
        # só a área que varia entre layouts (letras, dígitos, OEM, numpad); teclas E0 o
        # MapVirtualKey devolve sem o prefixo e confundiriam a tabela
        typing_area = (vk in (0x08, 0x09, 0x0D, 0x14, 0x20) or 0x30 <= vk <= 0x39 or 0x41 <= vk <= 0x5A
                       or 0x60 <= vk <= 0x6E or 0xBA <= vk <= 0xC2 or 0xDB <= vk <= 0xDF or vk == 0xE2)
        if not typing_area or sc > 0x7F:
            continue
        kc = _ATKBD_SPECIAL.get(sc, sc)
        if vk_to_keycode(vk, False) != kc:
            out[f"0x{vk:02X}"] = kc
    return out
