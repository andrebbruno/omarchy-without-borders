"""owb — Omarchy Without Borders command line (see `owb help`; strings in owb/i18n.py)."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys

from . import __version__
from .i18n import t

CONFIG = os.path.expanduser("~/.config/owb/config.json")
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "owb.sock")
SERVICE = "owb.service"
SOCKET = "owb.socket"


def _ctl(cmd: str, timeout: float = 30) -> str:
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
    except OSError:
        sys.exit(t("cli.not_running"))
    s.sendall(cmd.encode() + b"\n")
    out = b""
    while True:
        try:
            chunk = s.recv(65536)
        except socket.timeout:
            break
        if not chunk:
            break
        out += chunk
        if out.endswith(b"\n"):
            break
    return out.decode(errors="replace").strip()


def _gum() -> bool:
    """Use gum only on an interactive terminal; OWB_PLAIN=1 forces plain text mode."""
    return shutil.which("gum") is not None and sys.stdin.isatty() and not os.environ.get("OWB_PLAIN")


def _ask(prompt: str, default: str = "", password: bool = False) -> str:
    if _gum():
        args = ["gum", "input", "--prompt", f"{prompt} > ", "--value", default]
        if password:
            args.append("--password")
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(t("cli.cancelled"))
        return r.stdout.strip()
    import getpass
    if password:
        return getpass.getpass(f"{prompt}: ")
    v = input(f"{prompt} [{default}]: ").strip()
    return v or default


def _confirm(prompt: str, default: bool = True) -> bool:
    if _gum():
        r = subprocess.run(["gum", "confirm", "--default=" + ("true" if default else "false"), prompt])
        return r.returncode == 0
    v = input(f"{prompt} [{'Y/n' if default else 'y/N'}]: ").strip().lower()
    return default if not v else v.startswith("s") or v.startswith("y")


def _load() -> dict:
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.chmod(CONFIG, 0o600)


# ----------------------------------------------------------------------------- commands

def cmd_setup(_args):
    cfg = _load()
    print(t("cli.setup.title"))
    print(t("cli.setup.intro"))
    key = _ask(t("cli.setup.key"), cfg.get("key", ""), password=True)
    if len(key.replace(" ", "")) < 16:
        sys.exit(t("cli.setup.key_short"))
    name = _ask(t("cli.setup.name"),
                cfg.get("machine_name") or socket.gethostname().split(".")[0].upper()[:32]).upper()[:32]
    layout = _ask(t("cli.setup.layout"), cfg.get("keyboard_layout", "us"))
    peers = _ask(t("cli.setup.peers"), " ".join(cfg.get("peers", [])))
    port = _ask(t("cli.setup.port"), str(cfg.get("port", 15100)))
    crypto = "salted" if _confirm(t("cli.setup.dev"), False) else "legacy"
    cfg.update({"key": key, "machine_name": name, "keyboard_layout": layout, "peers": peers.split(),
                "port": int(port), "crypto": crypto, "share_clipboard": _confirm(t("cli.setup.clipboard"), True),
                "notifications": _confirm(t("cli.setup.notify"), True)})
    cfg.setdefault("language", "auto")
    _save(cfg)
    print("\n" + t("cli.setup.saved", path=CONFIG))
    ports = f"{int(port)}:{int(port) + 1}"
    if _confirm(t("cli.setup.ufw", port=ports), True):
        subprocess.run(["sudo", "ufw", "allow", f"{ports}/tcp"])
    if _confirm(t("cli.setup.enable"), True):
        cmd_enable(None)
        print(t("cli.setup.hint"))


def cmd_status(_args):
    st = json.loads(_ctl("status"))
    print(t("cli.status.head", ver=__version__, name=st["machine_name"], id=st["machine_id"],
            port=st["port"], crypto=st["crypto"], up=st["uptime_s"]))
    cap = t("cli.status.cap_on", edges=", ".join(st["edges"])) if st["capture"] else t("cli.status.cap_off")
    print(t("cli.status.line2", layout=st["keyboard_layout"], clip="on" if st["clipboard"] else "off", cap=cap))
    if st["controlling"]:
        print(t("cli.status.controlling", name=st["controlling"]))
    print(t("cli.status.conns"))
    if not st["peers"]:
        print(t("cli.status.none"))
    for p in st["peers"]:
        kind = t("cli.status.client") if p["client"] else t("cli.status.server")
        print(f"  {'✔' if p['trusted'] else '…'} {p['name']:<20} {p['addr']:<40} {kind}")
    names = [n or "—" for n in st["matrix"]]
    me = st["machine_name"].upper()
    cells = [f"[{n}]" if n.upper() == me else n for n in names]
    layout = t("cli.status.two_rows") if st.get("matrix_two_rows") else t("cli.status.one_row")
    if st.get("matrix_circle"):
        layout += t("cli.status.wrap")
    if st.get("matrix_two_rows"):
        print(t("cli.status.matrix") + " | ".join(cells[:2]) + f"   ({layout})")
        print(" " * len(t("cli.status.matrix").strip()) + " " + " | ".join(cells[2:]))
    else:
        print(t("cli.status.matrix") + " | ".join(cells) + f"   ({layout})")
    nb = st["neighbours"]
    if nb:
        print(t("cli.status.neighbours") + ", ".join(f"{k}={v}" for k, v in nb.items()))


def cmd_logs(args):
    cmd = ["journalctl", "--user", "-u", SERVICE, "-n", "100", "--no-pager"]
    if args and args[0] == "-f":
        cmd = ["journalctl", "--user", "-u", SERVICE, "-f"]
    os.execvp(cmd[0], cmd)


def cmd_keys(_args):
    print(t("cli.keys.intro"))
    cmd = ["journalctl", "--user", "-u", SERVICE, "-f", "-o", "cat", "--grep", "key vk|keycode|no VK|no keycode|sem VK|sem mapeamento"]
    os.execvp(cmd[0], cmd)


def cmd_test(args):
    if not args:
        sys.exit(t("cli.test.usage"))
    print(_ctl(f"run {args[0]} notepad {t('cli.test.msg')}", timeout=60))


def cmd_import_keymap(args):
    if not args:
        sys.exit(t("cli.import.usage"))
    from .vk_map import overrides_from_windows_keymap
    with open(args[0], encoding="utf-8-sig") as f:
        ov = overrides_from_windows_keymap(f.read())
    cfg = _load()
    cfg["vk_overrides"] = ov
    _save(cfg)
    print(t("cli.import.done", n=len(ov), path=CONFIG))
    if ov:
        print("  " + ", ".join(f"{k}->{v}" for k, v in ov.items()))
    print(t("cli.import.restart"))


def cmd_release(_args):
    print(_ctl("release"))


def cmd_enable(_args):
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    # the socket unit keeps the ports open while the service restarts (see systemd/owb.socket)
    subprocess.run(["systemctl", "--user", "enable", "--now", SOCKET], check=False)
    subprocess.run(["systemctl", "--user", "enable", "--now", SERVICE], check=False)
    subprocess.run(["systemctl", "--user", "--no-pager", "status", SERVICE, "-n", "5"], check=False)


def cmd_disable(_args):
    subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE, SOCKET], check=False)


def cmd_restart(_args):
    subprocess.run(["systemctl", "--user", "restart", SERVICE], check=False)
    subprocess.run(["systemctl", "--user", "--no-pager", "status", SERVICE, "-n", "5"], check=False)


def cmd_run(args):
    from .daemon import main
    main(args)


COMMANDS = {
    "setup": cmd_setup, "status": cmd_status, "logs": cmd_logs, "keys": cmd_keys, "test": cmd_test,
    "release": cmd_release, "import-keymap": cmd_import_keymap,
    "enable": cmd_enable, "disable": cmd_disable, "restart": cmd_restart, "run": cmd_run,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(t("cli.help"))
        return
    if argv[0] in ("-V", "--version"):
        print(f"owb {__version__}")
        return
    fn = COMMANDS.get(argv[0])
    if fn is None:
        sys.exit(t("cli.unknown", cmd=argv[0]) + "\n" + t("cli.help"))
    fn(argv[1:])


if __name__ == "__main__":
    main()
