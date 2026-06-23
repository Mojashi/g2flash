# g2flash

`g2flash.py` flashes firmware onto Even Realities G2 smart glasses by
reimplementing the official app's BLE flash protocol. It is the tool used to
push custom firmware (the `*_cfw.bin` images in this directory) onto the
device.

> **WARNING — this voids your warranty and can brick the glasses.**
> Flashing custom firmware over the OTA path carries a real risk of bricking
> the device. The tool makes you type `my warranty is void` at an interactive
> prompt before it will write anything (use `--my-warranty-is-void` to skip the
> prompt for automation). Only proceed if you understand and accept the risk.

## What's in this directory

- `g2flash.py` — the flasher.
- `g2_2.2.4.34.bin` — stock G2 2.2.4.34 firmware image (reference / re-flash).
- `g2_2.2.4.34_cfw.bin` — patched custom firmware.
- `g2_2.2.4.34_imgcontainer576.bin` — image-container 576×288 patch variant.
- `g2_2.2.4.34_NOTASKS.bin`, `g2_2.2.4.34_ramloader.bin` — other build variants.
- `patch_img_container_576.py` — the patch tool that produces the 576 variant.

## Requirements

- Python 3.x (developed against the Homebrew `python@3.14` build).
- One of two transports to reach the glasses:
  - **local** — this machine's own Bluetooth radio, via the `bleak` package.
  - **droidbridge** — a bonded Android phone running
    [DroidBridge](../droidbridge) that forwards GATT over HTTP/WebSocket; uses
    the `websocket-client` package.

Third-party Python dependencies:

| Package            | Needed for                          | Imported as |
|--------------------|-------------------------------------|-------------|
| `bleak`            | `g2://local` transport              | `bleak`     |
| `websocket-client` | `g2://droidbridge` transport        | `websocket` |

Both are imported lazily, so you only need to install the one for the transport
you actually use. Firmware parsing, validation, and `--recompute-checksums` run
on the standard library alone.

## Setting up the venv

The checked-in `venv/` is broken — its scripts point at a path that no longer
exists (`/Users/jbabcock/g2-mitm/venv/...`). Remove it and build a clean one:

```bash
cd g2flash

# remove the stale venv
rm -rf venv

# create and activate a fresh virtualenv
python3 -m venv venv
source venv/bin/activate          # bash/zsh
python -m pip install --upgrade pip

# insteal bleak for direct (local radio) flashing and websocket-client for DroidBridge flashing:
pip install bleak websocket-client
```

To leave the environment later, run `deactivate`. With the venv activated you
can invoke the tool as `python g2flash.py ...` (or
`./venv/bin/python g2flash.py ...` without activating).

### macOS note

On macOS, `bleak` talks to CoreBluetooth, which never exposes BLE MAC
addresses — scanned addresses are random per-host UUIDs. `g2flash` works around
this by scanning and matching the last three MAC bytes embedded in the arm's
advertised name (`Even G2_32_L_693CCB`). For a local flash the arm must be
powered on and **not** connected to the phone (quit the Even app / turn off the
phone's Bluetooth) so it advertises for a direct connection. The first time you
run it, macOS will prompt to grant your terminal Bluetooth permission.

## Usage

```
python g2flash.py -c <connection-string> -f <firmware.bin> [options]
```

Connection strings:

```
# direct from this machine's Bluetooth radio (needs bleak)
g2://local?left=<addr>&right=<addr>&addressType=public|random

# through a bonded phone running DroidBridge (needs websocket-client)
g2://droidbridge?phone=<host>&port=<port>&token=<tok>&left=<mac>&right=<mac>
```

`addressType=public` is a normal MAC (`D0:7A:47:82:09:67`); `random` is the
macOS/CoreBluetooth peripheral-UUID style.

Common options:

- `--lens left|right|both` — which arm to flash (default `both`).
- `--stop-before discover|heartbeat|file_check|flash|done` — dry-run gate that
  halts before the named stage; use it to test connectivity without writing.
- `--my-warranty-is-void` — skip the interactive warranty confirmation.
- `--component-retries N` / `--block-nak-retries N` — transfer retry tuning.
- `--debug` — print received BLE frames.

`--recompute-checksums IMAGE` rewrites an image's stored checksums in place
(component CRC32C + mainApp preamble CRC32) to match its current payloads and
exits without connecting. Run it after any length-preserving binary patch —
otherwise the glasses reject the component on END with status 7 (CHECK_FAIL).

### Examples

```bash
# dry run: connect to both arms over the local radio and stop before any write
python g2flash.py \
  -c 'g2://local?left=AA:BB:CC:11:22:33&right=AA:BB:CC:44:55:66&addressType=public' \
  -f g2_2.2.4.34.bin --stop-before flash

# fix checksums after patching, no device needed
python g2flash.py --recompute-checksums g2_2.2.4.34_cfw.bin

# flash the custom firmware to both arms via DroidBridge
python g2flash.py \
  -c 'g2://droidbridge?phone=192.168.1.50&port=8080&token=secret&left=AA:BB:CC:11:22:33&right=AA:BB:CC:44:55:66' \
  -f g2_2.2.4.34_cfw.bin
```

## How it works (brief)

The flasher speaks the same `aa21`-framed envelope protocol as the official
app, validated byte-for-byte against a real flash capture. The firmware image
is an EVENOTA container of five components; each is streamed over the firmware
data service (`...e1001`) as a FILE_CHECK subheader followed by 4 KB blocks,
then an END check the glasses verify against a per-component CRC32C. A heartbeat
on the EvenHub control service (`...e5450`) keeps the session alive during the
transfer. Arms are flashed one at a time. See the module docstring and comments
in `g2flash.py` for the wire-level details and the retry/recovery rationale.
