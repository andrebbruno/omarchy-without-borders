"""owb — linha de comando do Omarchy Without Borders.

  owb setup            assistente de configuração (chave, nome, layout, máquinas Windows)
  owb status           estado do daemon (conexões, matrix, quem está sendo controlado)
  owb logs [-f]        log do serviço (journalctl --user)
  owb keys             modo de depuração: mostra cada tecla recebida/traduzida
  owb test MAQUINA     abre o Bloco de Notas na máquina Windows e digita uma frase
  owb release          devolve o cursor ao Omarchy (se ficou preso controlando outra máquina)
  owb import-keymap F  gera vk_overrides a partir de um layout exportado do Windows (scripts/export-windows-keymap.ps1)
  owb enable|disable   habilita/desabilita o serviço systemd de usuário
  owb restart          reinicia o serviço
  owb run [-v]         executa o daemon em primeiro plano
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys

from . import __version__

CONFIG = os.path.expanduser("~/.config/owb/config.json")
SOCK = os.path.join(os.environ.get("XDG_RUNTIME_DIR", "/tmp"), "owb.sock")
SERVICE = "owb.service"


def _ctl(cmd: str, timeout: float = 30) -> str:
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(timeout)
    try:
        s.connect(SOCK)
    except OSError:
        sys.exit("daemon não está rodando (owb enable  ou  owb run)")
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
    """Assistente com gum só em terminal interativo; OWB_PLAIN=1 força o modo texto."""
    return shutil.which("gum") is not None and sys.stdin.isatty() and not os.environ.get("OWB_PLAIN")


def _ask(prompt: str, default: str = "", password: bool = False) -> str:
    if _gum():
        args = ["gum", "input", "--prompt", f"{prompt} > ", "--value", default]
        if password:
            args.append("--password")
        r = subprocess.run(args, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("cancelado")
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
    v = input(f"{prompt} [{'S/n' if default else 's/N'}]: ").strip().lower()
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


# ----------------------------------------------------------------------------- comandos

def cmd_setup(_args):
    cfg = _load()
    print("Omarchy Without Borders — configuração\n")
    print("No Windows: PowerToys → Mouse Without Borders. A chave de segurança e o nome desta\n"
          "máquina precisam estar lá (a chave é a mesma em todas as máquinas; o matrix é global —\n"
          "defina-o uma vez em qualquer Windows, incluindo o nome desta máquina).\n")
    key = _ask("Chave de segurança do MWB (16+ caracteres)", cfg.get("key", ""), password=True)
    if len(key.replace(" ", "")) < 16:
        sys.exit("chave precisa ter pelo menos 16 caracteres")
    name = _ask("Nome desta máquina (como aparece no matrix do Windows)",
                cfg.get("machine_name") or socket.gethostname().split(".")[0].upper()[:32]).upper()[:32]
    layout = _ask("Layout de teclado (xkb)", cfg.get("keyboard_layout", "br"))
    peers = _ask("IPs/nomes das máquinas Windows para conectar (separados por espaço; vazio = só aceitar conexões)",
                 " ".join(cfg.get("peers", [])))
    port = _ask("Porta base do MWB", str(cfg.get("port", 15100)))
    crypto = "salted" if _confirm("PowerToys é uma versão de desenvolvimento (branch main)?", False) else "legacy"
    cfg.update({"key": key, "machine_name": name, "keyboard_layout": layout, "peers": peers.split(),
                "port": int(port), "crypto": crypto, "share_clipboard": _confirm("Compartilhar clipboard?", True),
                "notifications": _confirm("Mostrar notificações?", True)})
    _save(cfg)
    print(f"\nconfig gravada em {CONFIG} (permissão 600)")
    if _confirm("Liberar a porta no ufw (sudo ufw allow %d/tcp)?" % (int(port) + 1), True):
        subprocess.run(["sudo", "ufw", "allow", f"{int(port) + 1}/tcp"])
    if _confirm("Habilitar e iniciar o serviço agora?", True):
        cmd_enable(None)
        print("\nDica: owb status  |  owb test NOME-DO-WINDOWS")


def cmd_status(_args):
    st = json.loads(_ctl("status"))
    print(f"Omarchy Without Borders v{__version__} — {st['machine_name']} (id {st['machine_id']}), "
          f"porta {st['port']}, cifra {st['crypto']}, up {st['uptime_s']} s")
    print(f"teclado {st['keyboard_layout']} · clipboard {'on' if st['clipboard'] else 'off'} · "
          f"captura {'ativa nas bordas ' + ', '.join(st['edges']) if st['capture'] else 'inativa'}")
    if st["controlling"]:
        print(f"CONTROLANDO: {st['controlling']}   (owb release para voltar)")
    print("\nconexões:")
    if not st["peers"]:
        print("  (nenhuma) — o Windows tem esta máquina no matrix e a mesma chave?")
    for p in st["peers"]:
        print(f"  {'✔' if p['trusted'] else '…'} {p['name']:<20} {p['addr']:<40} {'cliente' if p['client'] else 'servidor'}")
    names = [n or "—" for n in st["matrix"]]
    me = st["machine_name"].upper()
    print("\nmatrix: " + " | ".join(f"[{n}]" if n.upper() == me else n for n in names))
    nb = st["neighbours"]
    if nb:
        print("vizinhos: " + ", ".join(f"{k}={v}" for k, v in nb.items()))


def cmd_logs(args):
    cmd = ["journalctl", "--user", "-u", SERVICE, "-n", "100", "--no-pager"]
    if args and args[0] == "-f":
        cmd = ["journalctl", "--user", "-u", SERVICE, "-f"]
    os.execvp(cmd[0], cmd)


def cmd_keys(_args):
    print("mostrando teclas (Ctrl+C para sair) — pressione teclas no Windows apontando para esta máquina")
    cmd = ["journalctl", "--user", "-u", SERVICE, "-f", "-o", "cat", "--grep", "key vk|keycode|sem VK|sem mapeamento"]
    os.execvp(cmd[0], cmd)


def cmd_test(args):
    if not args:
        sys.exit("uso: owb test NOME-DA-MAQUINA-WINDOWS")
    print(_ctl(f"run {args[0]} notepad Omarchy Without Borders ok", timeout=60))


def cmd_import_keymap(args):
    if not args:
        sys.exit("uso: owb import-keymap keymap.txt   (gerado por scripts/export-windows-keymap.ps1 no Windows)")
    from .vk_map import overrides_from_windows_keymap
    with open(args[0], encoding="utf-8-sig") as f:
        ov = overrides_from_windows_keymap(f.read())
    cfg = _load()
    cfg["vk_overrides"] = ov
    _save(cfg)
    print(f"{len(ov)} tecla(s) diferem da tabela embutida; vk_overrides gravado em {CONFIG}")
    if ov:
        print("  " + ", ".join(f"{k}->{v}" for k, v in ov.items()))
    print("reinicie: owb restart")


def cmd_release(_args):
    print(_ctl("release"))


def cmd_enable(_args):
    subprocess.run(["systemctl", "--user", "daemon-reload"])
    subprocess.run(["systemctl", "--user", "enable", "--now", SERVICE], check=False)
    subprocess.run(["systemctl", "--user", "--no-pager", "status", SERVICE, "-n", "5"], check=False)


def cmd_disable(_args):
    subprocess.run(["systemctl", "--user", "disable", "--now", SERVICE], check=False)


def cmd_restart(_args):
    subprocess.run(["systemctl", "--user", "restart", SERVICE], check=False)
    subprocess.run(["systemctl", "--user", "--no-pager", "status", SERVICE, "-n", "5"], check=False)


def cmd_run(args):
    from .daemon import main
    main(args)


COMMANDS = {
    "setup": cmd_setup, "status": cmd_status, "logs": cmd_logs, "keys": cmd_keys, "test": cmd_test,
    "release": cmd_release, "import-keymap": cmd_import_keymap, "enable": cmd_enable, "disable": cmd_disable, "restart": cmd_restart, "run": cmd_run,
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    if argv[0] in ("-V", "--version"):
        print(f"owb {__version__}")
        return
    fn = COMMANDS.get(argv[0])
    if fn is None:
        sys.exit(f"comando desconhecido: {argv[0]}\n{__doc__}")
    fn(argv[1:])


if __name__ == "__main__":
    main()
