"""Minimal i18n: English is the source language; pt-BR provided. Language comes from
config "language" ("en" | "pt-BR" | "auto"), else from LANG/LC_ALL (pt_* → pt-BR)."""
from __future__ import annotations

import json
import os

_PT = {
    # cli
    "cli.help": """owb — Omarchy Without Borders command line.

  owb setup            configuration wizard (key, name, layout, Windows machines)
  owb status           daemon state (connections, matrix, who is being controlled)
  owb logs [-f]        service log (journalctl --user)
  owb keys             debug mode: show every key received/translated
  owb test MACHINE     open Notepad on the Windows machine and type a sentence
  owb release          give the cursor back to Omarchy (if stuck controlling another machine)
  owb import-keymap F  build vk_overrides from a Windows keyboard layout export (scripts/export-windows-keymap.ps1)
  owb enable|disable   enable/disable the systemd user service
  owb restart          restart the service
  owb run [-v]         run the daemon in the foreground
""",
    "cli.not_running": "daemon is not running (owb enable  or  owb run)",
    "cli.cancelled": "cancelled",
    "cli.setup.title": "Omarchy Without Borders — setup\n",
    "cli.setup.intro": ("On Windows: PowerToys → Mouse Without Borders. The security key and this machine's\n"
                        "name must be there (same key on every machine; the matrix is global — define it\n"
                        "once on any Windows machine, including this machine's name).\n"),
    "cli.setup.key": "MWB security key (16+ characters)",
    "cli.setup.key_short": "the key must be at least 16 characters long",
    "cli.setup.name": "This machine's name (as it appears in the Windows matrix)",
    "cli.setup.layout": "Keyboard layout (xkb)",
    "cli.setup.peers": "IPs/names of Windows machines to connect to (space separated; empty = only accept connections)",
    "cli.setup.port": "MWB base port",
    "cli.setup.dev": "Is PowerToys a development build (main branch)?",
    "cli.setup.clipboard": "Share clipboard?",
    "cli.setup.notify": "Show notifications?",
    "cli.setup.saved": "config written to {path} (mode 600)",
    "cli.setup.ufw": "Open the port in ufw (sudo ufw allow {port}/tcp)?",
    "cli.setup.enable": "Enable and start the service now?",
    "cli.setup.hint": "\nTip: owb status  |  owb test WINDOWS-NAME",
    "cli.status.head": "Omarchy Without Borders v{ver} — {name} (id {id}), port {port}, cipher {crypto}, up {up} s",
    "cli.status.line2": "keyboard {layout} · clipboard {clip} · capture {cap}",
    "cli.status.cap_on": "active on edges {edges}",
    "cli.status.cap_off": "inactive",
    "cli.status.controlling": "CONTROLLING: {name}   (owb release to return)",
    "cli.status.conns": "\nconnections:",
    "cli.status.none": "  (none) — does Windows have this machine in the matrix and the same key?",
    "cli.status.client": "client",
    "cli.status.server": "server",
    "cli.status.matrix": "\nmatrix: ",
    "cli.status.neighbours": "neighbours: ",
    "cli.keys.intro": "showing keys (Ctrl+C to quit) — press keys on Windows while pointing at this machine",
    "cli.test.usage": "usage: owb test WINDOWS-MACHINE-NAME",
    "cli.test.msg": "Omarchy Without Borders ok",
    "cli.import.usage": "usage: owb import-keymap keymap.txt   (from scripts/export-windows-keymap.ps1 on Windows)",
    "cli.import.done": "{n} key(s) differ from the built-in table; vk_overrides written to {path}",
    "cli.import.restart": "restart: owb restart",
    "cli.unknown": "unknown command: {cmd}",
    # daemon
    "d.connected": "Connected to {name}",
    "d.badkey": "Security key mismatch",
    "d.badkey_body": "{addr} rejected the handshake",
    "d.controlling": "Controlling {name}",
    "d.controlling_body": "move the mouse back across the edge to return",
    "d.appname": "Omarchy Without Borders",
}

_PT_BR = {
    "cli.help": """owb — linha de comando do Omarchy Without Borders.

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
""",
    "cli.not_running": "daemon não está rodando (owb enable  ou  owb run)",
    "cli.cancelled": "cancelado",
    "cli.setup.title": "Omarchy Without Borders — configuração\n",
    "cli.setup.intro": ("No Windows: PowerToys → Mouse Without Borders. A chave de segurança e o nome desta\n"
                        "máquina precisam estar lá (a chave é a mesma em todas as máquinas; o matrix é global —\n"
                        "defina-o uma vez em qualquer Windows, incluindo o nome desta máquina).\n"),
    "cli.setup.key": "Chave de segurança do MWB (16+ caracteres)",
    "cli.setup.key_short": "a chave precisa ter pelo menos 16 caracteres",
    "cli.setup.name": "Nome desta máquina (como aparece no matrix do Windows)",
    "cli.setup.layout": "Layout de teclado (xkb)",
    "cli.setup.peers": "IPs/nomes das máquinas Windows para conectar (separados por espaço; vazio = só aceitar conexões)",
    "cli.setup.port": "Porta base do MWB",
    "cli.setup.dev": "O PowerToys é uma versão de desenvolvimento (branch main)?",
    "cli.setup.clipboard": "Compartilhar clipboard?",
    "cli.setup.notify": "Mostrar notificações?",
    "cli.setup.saved": "config gravada em {path} (permissão 600)",
    "cli.setup.ufw": "Liberar a porta no ufw (sudo ufw allow {port}/tcp)?",
    "cli.setup.enable": "Habilitar e iniciar o serviço agora?",
    "cli.setup.hint": "\nDica: owb status  |  owb test NOME-DO-WINDOWS",
    "cli.status.head": "Omarchy Without Borders v{ver} — {name} (id {id}), porta {port}, cifra {crypto}, up {up} s",
    "cli.status.line2": "teclado {layout} · clipboard {clip} · captura {cap}",
    "cli.status.cap_on": "ativa nas bordas {edges}",
    "cli.status.cap_off": "inativa",
    "cli.status.controlling": "CONTROLANDO: {name}   (owb release para voltar)",
    "cli.status.conns": "\nconexões:",
    "cli.status.none": "  (nenhuma) — o Windows tem esta máquina no matrix e a mesma chave?",
    "cli.status.client": "cliente",
    "cli.status.server": "servidor",
    "cli.status.matrix": "\nmatrix: ",
    "cli.status.neighbours": "vizinhos: ",
    "cli.keys.intro": "mostrando teclas (Ctrl+C para sair) — pressione teclas no Windows apontando para esta máquina",
    "cli.test.usage": "uso: owb test NOME-DA-MAQUINA-WINDOWS",
    "cli.test.msg": "Omarchy Without Borders ok",
    "cli.import.usage": "uso: owb import-keymap keymap.txt   (gerado por scripts/export-windows-keymap.ps1 no Windows)",
    "cli.import.done": "{n} tecla(s) diferem da tabela embutida; vk_overrides gravado em {path}",
    "cli.import.restart": "reinicie: owb restart",
    "cli.unknown": "comando desconhecido: {cmd}",
    "d.connected": "Conectado a {name}",
    "d.badkey": "Chave de segurança diferente",
    "d.badkey_body": "{addr} rejeitou o handshake",
    "d.controlling": "Controlando {name}",
    "d.controlling_body": "mova o mouse de volta pela borda para retornar",
    "d.appname": "Omarchy Without Borders",
}

_TABLES = {"en": _PT, "pt-BR": _PT_BR}
_lang: str | None = None


def detect_language(config_path: str = "~/.config/owb/config.json") -> str:
    p = os.path.expanduser(config_path)
    try:
        with open(p, encoding="utf-8") as f:
            v = json.load(f).get("language", "auto")
        if v in _TABLES:
            return v
    except (OSError, ValueError):
        pass
    for var in ("LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var, "")
        if val:
            return "pt-BR" if val.lower().startswith("pt") else "en"
    return "en"


def language() -> str:
    global _lang
    if _lang is None:
        _lang = detect_language()
    return _lang


def set_language(lang: str) -> None:
    global _lang
    _lang = lang if lang in _TABLES else "en"


def t(key: str, **kw) -> str:
    s = _TABLES.get(language(), _PT).get(key) or _PT.get(key, key)
    return s.format(**kw) if kw else s
