# Omarchy Without Borders

[English](README.md) · **Português (Brasil)**

Cliente Linux/Wayland do **Mouse Without Borders** (PowerToys). Compartilhe mouse, teclado e
clipboard entre um PC Omarchy/Hyprland e máquinas Windows **sem instalar nada no Windows** além do
PowerToys original — útil quando o Windows é uma máquina corporativa que não aceita software extra.

- Windows → Linux: o Windows controla o Omarchy (mouse absoluto, teclado, roda).
- Linux → Windows: o Omarchy controla o Windows ao cruzar a borda da tela (captura nativa do Hyprland).
- Clipboard de texto e imagem PNG nos dois sentidos (até 1 MB, o modo "inline" do MWB).
- Matrix de uma ou duas linhas, circular ou não, exatamente como configurado no Windows.
- Fala o protocolo nativo do MWB (TCP 15101, AES‑256‑CBC/PBKDF2, mesma chave de segurança).

Compatível com PowerToys 0.9x–0.100.x (cifra "legacy") e com o branch `main` (`crypto: "salted"`).

## Requisitos

- Hyprland ≥ 0.50 (protocolos `zwlr_virtual_pointer_v1`, `zwp_virtual_keyboard_v1`,
  `hyprland_input_capture_v1`) — o Omarchy 4 já atende.
- `libei`, `wl-clipboard`, `python-pywayland`, `python-cryptography`, `python-xkbcommon`, `libnotify`.
- Opcional: `gum` (assistente), `ufw`.

## Instalação

Arch/Omarchy (AUR, quando publicado): `yay -S omarchy-without-borders`

Manual:

```sh
sudo pacman -S --needed python-pywayland python-cryptography python-xkbcommon libei wl-clipboard libnotify gum
pipx install .            # ou: pip install --user .
install -Dm644 systemd/owb.service ~/.config/systemd/user/owb.service
owb setup
```

## No Windows (PowerToys → Mouse Without Borders)

1. Anote a **chave de segurança** (a mesma em todas as máquinas).
2. Adicione o **nome da máquina Linux** (maiúsculas, ex.: `OMARCHY-VM`) no matrix.
   O matrix é global: quem aplica configurações retransmite o dele para todas as máquinas — defina‑o
   uma vez, em qualquer Windows, e não mantenha cópias divergentes.
3. Se o Windows não resolver o nome do Linux pela rede (LLMNR/mDNS), use **IP address mapping**:
   `OMARCHY-VM 192.168.x.y`.
4. Máquinas com firewall corporativo costumam só aceitar conexões **de saída**; nesse caso é o Windows
   que conecta no Linux (porta 15101 precisa estar liberada aqui). O MWB só redisca uma máquina sozinho
   depois de um *reset* de conexão, quando o matrix muda ou quando alguém conecta nele — por isso o
   daemon fecha os sockets com reset ao reiniciar, e o Windows reconecta em um ou dois segundos. Se
   mesmo assim não reconectar, `Ctrl+Alt+R` (Reconnect) no Windows.

## Uso

```
owb status            conexões, matrix, quem está sendo controlado
owb test DESKTOP-X    abre o Bloco de Notas na máquina e digita uma frase (teste ponta a ponta)
owb keys              depuração de mapeamento de teclas
owb logs -f           log do serviço
owb release           devolve o cursor se ficou preso controlando outra máquina
```

Config: `~/.config/owb/config.json` (permissão 600 — contém a chave).

| chave | padrão | |
|---|---|---|
| `key` | | chave de segurança do MWB |
| `machine_name` | hostname | nome no matrix |
| `peers` | `[]` | IPs/hosts Windows a que conectamos (além de aceitar conexões) |
| `port` | 15100 | porta base; mensagens em porta+1 |
| `crypto` | `legacy` | `salted` para PowerToys de desenvolvimento |
| `keyboard_layout` | `us` | layout xkb usado para injetar teclas (ex.: `br`) |
| `language` | `auto` | `en` ou `pt-BR` para CLI/notificações (`auto` segue o `LANG`) |
| `vk_overrides` | `{}` | `{"0xBA": 39}` — ajuste tecla a tecla (VK → keycode evdev) |
| `share_clipboard` | true | |
| `notifications` | true | |
| `host_mode` | true | captura nas bordas (Linux controlando Windows) |
| `matrix` | | último matrix recebido (atualizado automaticamente) |

## Limitações conhecidas

- Clipboard > 1 MB e transferência de arquivos (socket 15100 do MWB) ainda não implementados.
- Só Hyprland por enquanto (a captura usa `hyprland_input_capture_v1`); GNOME/KDE exigiriam o
  portal `InputCapture` + libei — mesma biblioteca, outra negociação.
- A cifra do MWB lançado usa IV fixo (decisão do MWB, não nossa); use uma chave forte.

## Licença

MIT. A compatibilidade de protocolo foi derivada do código do PowerToys (Microsoft, MIT).
Não é um produto da Microsoft.
