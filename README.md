# Omarchy Without Borders

**English** · [Português (Brasil)](README.pt-BR.md)

A Linux/Wayland client for **Mouse Without Borders** (Microsoft PowerToys). Share mouse, keyboard
and clipboard between an Omarchy/Hyprland PC and Windows machines **without installing anything on
Windows** beyond the stock PowerToys — handy when the Windows box is a locked-down corporate laptop.

- Windows → Linux: Windows drives Omarchy (absolute mouse, keyboard, wheel).
- Linux → Windows: Omarchy drives Windows when the cursor crosses a screen edge (native Hyprland
  input capture).
- Clipboard in both directions: text and PNG images of any size, and **files** (up to MWB's
  100 MB), using MWB's inline mode below 1 MB and its port‑15100 transfer above it. Files
  received from Windows land in `~/Downloads/OmarchyWithoutBorders/` and go on the clipboard
  as `text/uri-list`; a file copied on Linux appears in the Windows clipboard as a file.
- Matrix with one or two rows, with or without wrap-around, exactly as configured on Windows.
- Speaks the native MWB protocol: TCP 15101, AES‑256‑CBC/PBKDF2, the same security key.

Works with PowerToys 0.9x–0.100.x (legacy cipher) and with the `main` branch (`crypto: "salted"`).

## Requirements

- Hyprland ≥ 0.50 (`zwlr_virtual_pointer_v1`, `zwp_virtual_keyboard_v1`,
  `hyprland_input_capture_v1`) — Omarchy 4 ships all of it.
- `libei`, `wl-clipboard`, `python-pywayland`, `python-cryptography`, `python-xkbcommon`, `libnotify`.
- Optional: `gum` (setup wizard), `ufw`.

## Install

Arch/Omarchy (AUR, once published): `yay -S omarchy-without-borders`

Manual:

```sh
sudo pacman -S --needed python-pywayland python-cryptography python-xkbcommon libei wl-clipboard libnotify gum
pipx install .            # or: pip install --user .
install -Dm644 systemd/owb.service ~/.config/systemd/user/owb.service
install -Dm644 systemd/owb.socket ~/.config/systemd/user/owb.socket
owb setup
```

Omarchy bar widget (status, machines, actions):

```sh
omarchy plugin add https://github.com/andrebbruno/omarchy-without-borders.git --enable   # manifest.json is at the repo root
omarchy bar put br.andrebruno.owb --section right
```

## On Windows (PowerToys → Mouse Without Borders)

1. Note the **security key** (the same on every machine).
2. Add the **Linux machine name** (uppercase, e.g. `OMARCHY-VM`) to the matrix.
   The matrix is global: whichever machine applies settings broadcasts its matrix to all the others —
   define it once, on any Windows machine, and don't keep diverging copies.
3. If Windows can't resolve the Linux name (LLMNR/mDNS), use **IP address mapping**:
   `OMARCHY-VM 192.168.x.y`.
4. Corporate laptops usually only allow **outbound** connections; then it is Windows that connects to
   Linux (port 15101 must be open here). MWB only re-dials a machine by itself after a connection
   *reset*, when the matrix changes, or when someone connects to it — so the daemon closes its
   sockets with a reset on restart, and Windows reconnects within a couple of seconds. If it still
   doesn't, `Ctrl+Alt+R` (Reconnect) on Windows.

## Usage

```
owb status            connections, matrix, who is being controlled
owb test DESKTOP-X    opens Notepad on that machine and types a sentence (end-to-end test)
owb keys              key-mapping debug
owb logs -f           service log
owb release           give the cursor back if it got stuck controlling another machine
owb matrix A B C      set the machine order on every machine (--two-rows, --wrap; "-" = empty slot)
owb restart           restart the service (ports stay open through owb.socket, so Windows re-dials)
owb import-keymap F   vk_overrides from a Windows layout export (scripts/export-windows-keymap.ps1)
```

Config: `~/.config/owb/config.json` (mode 600 — contains the key).

| key | default | |
|---|---|---|
| `key` | | MWB security key |
| `machine_name` | hostname | name in the matrix |
| `peers` | `[]` | Windows IPs/hosts we connect to (besides accepting connections) |
| `port` | 15100 | base port; messages on port+1 |
| `crypto` | `legacy` | `salted` for PowerToys development builds |
| `keyboard_layout` | `us` | xkb layout used to inject keys (e.g. `br`) |
| `vk_overrides` | `{}` | `{"0xBA": 39}` — per-key fix (VK → evdev keycode) |
| `language` | `auto` | `en` or `pt-BR` for CLI/notifications (`auto` follows `LANG`) |
| `share_clipboard` | true | |
| `notifications` | true | |
| `host_mode` | true | edge capture (Linux driving Windows) |
| `matrix` | | last matrix received (kept up to date automatically) |

The bar widget follows `LANG` too (pt-BR or English).

## Known limitations

- Big clipboard/file transfers are fetched *when you switch machines* (that's how MWB works: the
  owner only announces, and the machine you move to pulls within 30 s).
- PowerToys' *service mode* ("Use Service" in the MWB settings, needed only to control the
  Windows lock screen/UAC prompts) breaks MWB's own clipboard for images, texts over a few hundred
  KB and files — nothing big leaves Windows, even to another Windows. With it **off**, images, big
  texts and files from Windows all arrive here (validated with PowerToys 0.100.2).
- Hyprland only for now (capture uses `hyprland_input_capture_v1`); GNOME/KDE would need the
  `InputCapture` portal + libei — same library, different negotiation.
- The released MWB cipher uses a fixed IV (MWB's decision, not ours); use a strong key.

## How it works

The daemon (`owb run`) keeps one encrypted TCP connection per Windows machine, answers the MWB
handshake with the shared key, and:

- injects incoming `Mouse`/`Keyboard` packets through the compositor's virtual pointer/keyboard;
- registers screen-edge barriers with `hyprland_input_capture_v1`; when the cursor crosses one, the
  compositor hands input over an EIS (libei) socket, which is translated to MWB packets with a
  virtual cursor, until it crosses back;
- watches the local clipboard (`wl-paste --watch`) and applies remote clipboard data (`wl-copy`).

Everything else (matrix, machine names, hotkeys) is decided by the Windows side, as in MWB.

## License

MIT. Protocol compatibility was derived from the PowerToys source (Microsoft, MIT).
Not a Microsoft product.
