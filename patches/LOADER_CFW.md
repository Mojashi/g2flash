# G2 mode-runtime loader CFW (firmware 2.2.4.34)

A CFW you flash **once**. Thereafter it receives arbitrary "mode" code payloads over BLE
into RAM and runs them, exposing an API table of firmware primitives. Every feature
(debug, screenshot, differential/compressed display, stereo, animation, wireframe, …)
becomes a **hot-loaded payload** — no re-flash, safe iteration, and the payloads are
firmware-version-independent because they only ever call through the API table.

## Why the 2.2.4.34 base is the safe one

2.2.4.34's OTA container has a **single** Apollo510 app code component
(`ota/s200_firmware_ota.bin`), so a payload byte at file offset `K` maps linearly to
runtime address `K + 0x39E680` across the whole component — the disassembler base and the
runtime base are identical. (2.2.6.10 split the app into two code components at different
load bases, so a single base no longer equals the runtime base; every derived address then
needs a per-component correction, which is the brick risk we backed away from.)

### It is not brick-able in normal use
- **The only brick-critical step is container assembly** (`patch_loader.py`), and it reuses
  the exact append / preamble-length / ps / TOC / CRC fixup order proven by
  `patch_compress.py` (the builder the currently-flashed CFW was made with). The output
  passes `g2flash.validate_firmware` + `check_mainapp_fits_mram` before you ever flash.
- **Everything the loader does at runtime is recoverable.** A bad payload, wrong cache op,
  or bad anchor at worst hard-faults into a watchdog reset back into this same valid CFW.
- **The loader is fully dormant** unless a frame arrives on `RUNTIME_SID` (0x7b): for every
  other sid `rt_rx_hook` does zero work and tail-calls the stock dispatcher, so the glasses
  boot and behave byte-for-byte stock, and OTA re-flash from the app is always reachable.
  → not even soft-brick-able.

Reconnecting the official Even app upgrades the firmware and wipes the mod (uninstall path).

## Build

```
cd g2flash
python3 patches/patch_loader.py            # -> g2_2.2.4.34_loader.bin (+ patches/loader_patches.json)
```

`patch_loader.py` compiles `runtime_main_22434.c` (via `build.py`, the PIC mini-linker),
appends the ~2.3 KB blob to the tail of the main-app payload, applies the **single** MRAM
edit — redirect `bl 0x441c68` at `0x0045aaa4` (the universal inbound-frame dispatcher call,
the same proven site the screenshot CFW used) to `rt_rx_hook` — then fixes the container
metadata and recomputes CRCs. It refuses an image that would pass the MRAM ceiling.

## Flash (you do this; ~13 min/full image, BLE)

Same path as the other CFWs. Both lenses. Use `PYTHONUNBUFFERED=1` for live progress. See
`g2flash.py`. The loader does not depend on a GitHub remote or the phone app.

## Protocol (BLE sid 0x7b, `RT_OP_*` in fw_2.2.4.34.h)

All frames are the aa21 payload; each command is sized to fit one ~232-byte chunk.
Reply frames (loader/payload → host, on sid 0x7b) always start with `RT_MAGIC` 0xA7.

| op | opcode | wire | action |
|----|--------|------|--------|
| LOAD_FRAG | 0x01 | `[01][mode][idx u16 LE][last u8][bytes…]` | `idx==0` frees old buf + starts a fresh 16 KiB code buffer, then appends; later idx append. |
| ACTIVATE | 0x02 | `[02][mode][total_len u32 LE][crc32 u32 LE]` | verify length **and** CRC-32 of the buffer, inline dcache-clean + icache-invalidate, jump to `entry(&api)` at buffer offset 0. Reply `[A7][02][active]`. Short frame → `[A7][E0]`. |
| SEND | 0x03 | `[03][mode][data…]` | active mode's `on_data(data,len)`. |
| RESET | 0x04 | `[04]` | exit active mode (`exit()`), free buffers. |
| PING | 0x05 | `[05]` | reply `[A7][05][active]`. |

The CRC-in-ACTIVATE is a safety gate: a dropped/reordered fragment fails it and **nothing
executes**.

### Host client

```
cd demos
bun runtime.ts load ../obj/mode_selftest.text.bin   # upload + ACTIVATE (computes len+crc32)
bun runtime.ts ping                                 # liveness -> [A7 05 active]
bun runtime.ts send 1 "hello"                        # -> mode on_data
bun runtime.ts reset
```
Traffic rides the transmit lens (R arm); the loader's `api_reply` self-gates to it.

## Writing a payload (mode)

`mode_selftest.c` is the reference template. Hard rules (enforced by `build.py`):
- **No writable globals / static tables** — `.data`/`.bss` produce absolute relocations the
  PIC linker rejects. Fill the vtable at runtime (`&fn` under `-fropi` → PC-relative, fixed
  up in-blob). Persist per-mode state in a heap block from `api->mem_alloc`, and stash its
  pointer in the one fixed scratch word `RT_MODE_CTX_SLOT_A` (0x20053404) — **never** the
  loader anchor 0x20053304.
- **Call only through `api`** — zero absolute firmware calls.
- **Entry at blob offset 0** — a naked `_start: b.w payload_entry` defined first guarantees
  it; `payload_entry(api)` returns the mode vtable.
- **Free what you alloc** — the loader frees only the code buffer, so free your ctx in
  `exit()` (recover it from the scratch slot, which still holds it when `exit()` runs).

### API table (`rt_api`, keep byte-identical to runtime.c)
`abi_version`, `mem_alloc`, `mem_free`, `send(sid,ptr,len)`, `reply(ptr,len)`,
`lens_side()` (2=L,1=R), `tick_ms()`, `fb_canvas()` (640×480 4bpp, 2px/byte),
`present()` (dcache-clean whole canvas), `dcache_clean(ptr,len)`, `fb_w`, `fb_h`.
Mode vtable: `init(api)`, `tick(dt_ms)`, `on_input(record)`, `on_data(buf,len)`, `exit()`.

## v1 scope and roadmap

v1 is deliberately minimal: **one** MRAM patch (the RX-hook redirect), inline cache
maintenance (no derived firmware cache fn), and **no timer / no input hook**. Payloads
animate via host-driven `SEND` frames for now. A v2 loader can add an on-device osTimer
tick and an input-dispatcher trampoline — pure additions, no ABI change — once their
firmware addresses are derived + verified. **Before** arming any concurrent callback, the
one-generation deferred-free and the publish-before-`init` window in `runtime.c` must be
hardened (see the V2 CAVEAT there).

## Verification status

- Container: `validate_firmware` OK, `check_mainapp_fits_mram` OK, 385 KB under the MRAM
  ceiling. Blob 2336 B.
- Logic: Unicorn emulation (`scratchpad/verify_loader_22434.py`, firmware stubbed by
  address) — LOAD_FRAG → ACTIVATE (len+CRC + inline cache + jump) → payload marker + canvas
  draw, SEND echo, PING mode-active, and a full reload cycle, all PASS.
- Adversarial review (12-agent workflow, 2026-07-18): **0 brick, 0 crash** confirmed. The
  anchor was proven safe by tracing the firmware's allocator descriptors (all arenas ≥
  0x20142330, ~950 KB above the anchor). Two minor issues found and fixed (a stale hook-site
  comment; a payload ctx leak in the selftest's `exit`).

Not yet flashed to hardware — flash when BLE is free.
