# G2 reverse-engineering notes

Field notes from reverse-engineering the Even Realities G2 smart glasses
firmware (versions **2.2.4.34** and **2.2.6.10**) and building custom firmware
(CFW) on top of it. These are the durable findings — architecture, wire
formats, addresses, and the "what works / what fails" list — distilled from the
work in this repo.

They complement the more formal write-ups already in [`docs/`](../):
`FW_ARCH_2.2.4.34.md`, `terminal-protocol.md`, `peer_comms_map.md`,
`pb_schema*.{json,proto}`, and the reusable headers in
[`../../patches/`](../../patches/).

## Contents

| Note | Topic |
|------|-------|
| [01 — Hardware & dev facts](01-hardware-and-dev-facts.md) | Panel, two-arm BLE topology, display constraints, library landscape |
| [02 — RE toolchain (Ghidra DB)](02-re-toolchain.md) | How the Ghidra DB is named/typed/rebuilt, LVGL reference matching, protobuf extraction |
| [03 — Display architecture](03-display-architecture.md) | Stock LVGL v9.3, compositor, panel power, what payload-display approaches work vs reboot |
| [04 — Two lenses & cross-lens sync](04-two-lens-and-sync.md) | Master/slave BLE peer link, arm routing, `send_data_to_peer`, native and custom L/R sync |
| [05 — CFW loader & hot-loaded modes](05-cfw-loader-and-modes.md) | The "flash once, hot-load code over BLE" loader, own-mode full-screen rendering, 3D stereo + IMU |
| [06 — Terminal protocol & protobuf](06-terminal-and-protobuf.md) | Terminal-mode hijack, nanopb schema recovery, `g2ctl` settings CLI, IMU over BLE |
| [07 — Full-panel stereo tiling](07-stereo-tiling.md) | Driving 576×288 stereo 3D via the image mode-4 path |

## Working principle: RE findings go into the DB, not just docs

When reverse-engineering produces durable knowledge (a function's purpose, a
signature, a struct layout, a protocol), it is applied **back into the Ghidra
database** — as USER_DEFINED names, typed signatures, struct types, and plate
comments — via an `apply_*.py` script wired into
[`../../ghidra/rebuild_db.sh`](../../ghidra/rebuild_db.sh), not left only in a
markdown file. The DB is the compounding asset: every future decompile reads
against it, so knowledge that lives only in a `.md` has to be re-derived. The
doc and the DB apply are both deliverables — the doc for reading, the DB for
working.

> The Ghidra project database itself (`ghidra/ghidra_proj/`, ~125 MB) is
> **not** committed — it is a generated artifact. Rebuild it from the firmware
> with `ghidra/rebuild_db.sh`, which re-applies the `apply_*.py` scripts.
