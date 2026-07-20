# 05 — CFW loader & hot-loaded modes

Rather than porting each CFW feature as its own firmware patch, the architecture
is a **loader / "mode-runtime" CFW**: flash **once** per firmware version, then
every feature is a **hot-loaded code payload** delivered over BLE into RAM and
run via an API table of firmware primitives. No re-flash per feature, safe, and
largely firmware-version-independent.

## Why it is low-risk

The **only** brick-critical step is container assembly
([`patches/patch_loader.py`](../../patches/patch_loader.py), which reuses the
proven `patch_compress.py` append / preamble / TOC / CRC path). Every **runtime**
fault (bad payload, cache, anchor) is a recoverable watchdog reset, **not** a
brick — the loader is dormant unless a frame arrives on `RUNTIME_SID 0x7b` (else
it tail-calls the stock dispatcher), so the glasses boot and behave stock, and
OTA re-flash is always reachable. Not even soft-brickable.

## Why 2.2.4.34 (not 2.2.6.10) as the loader base

The 2.2.6.10 container has **two** Apollo510 code components at different load
bases, so a single disasm base ≠ runtime base and the per-component correction
kept producing garbage → real brick risk (that CFW image was renamed
`*_cfw.REJECTED-BRICK-DO-NOT-FLASH.bin`). **2.2.4.34 has a single app code
component** (`ota/s200_firmware_ota.bin`), so runtime = `file_off + 0x39E680`
across the whole image — no per-component correction, the brick problem simply
does not exist.

> **2.2.6.10 parity fact:** its main app sits at an odd file offset (bootloader
> component added), so its real load base is `0x39E67F` (odd), but a NEW address
> = `file_off + 0x39E680` is the correct Thumb function pointer usable directly.
> For disasm/patch, `file_off = value − 0x39E680` **without** clearing the low
> bit (unlike 2.2.4.34). Some RAM globals also moved regions — re-derive, don't
> assume. Full map: [`patches/addrmap_2.2.6.10.json`](../../patches/addrmap_2.2.6.10.json)
> (40/40 high-confidence, derived by a per-address derive→adversarial-verify
> workflow).

## The v1 loader = RX-hook-only

A single MRAM patch: redirect the `bl 0x441c68` at `0x0045aaa4` (the universal
inbound-dispatcher site the screenshot CFW also used) → `rt_rx_hook`. Inline
cache maintenance (DCCMVAC clean + ICIALLU). No timer, no input trampoline in v1
(payloads animate via host `RT_OP_SEND`).

**Protocol on sid `0x7b`** (replies lead with `0xA7`):
`LOAD_FRAG(01)` / `ACTIVATE(02, len+crc32)` / `SEND(03)` / `RESET(04)` /
`PING(05)`.

Key 2.2.4.34 addresses (all binary-confirmed by prologue disasm, in
[`patches/fw_2.2.4.34.h`](../../patches/fw_2.2.4.34.h)): `malloc 0x472b6f`,
`free 0x472bb3`, `send 0x47398d`, `side 0x45a8ed`, `tick 0x448139`,
`dispatch 0x441c69`, canvas ptr `0x20074464`, initial MSP `0x2007fb00`. Loader
state anchor `0x20053304`, payload ctx slot `0x20053404` (distinct — fixes the
2.2.6.10 bug where both used one slot and the payload clobbered the loader's
state), chosen from a literal-reference-free SRAM gap and magic-checked
(`RT_STATE_MAGIC "RTM1"`) so a collision degrades to cold-boot, not crash.

Files: [`patches/`](../../patches/) `fw_2.2.4.34.h`, `runtime.c`,
`runtime_state.h`, `runtime_hooks_22434.c`, `runtime_main_22434.c`,
`mode_selftest.c`, `patch_loader.py`. Output `g2_2.2.4.34_loader.bin`.

**Flashed + verified on hardware:** loader alive (`runtime.ts ping` →
`«rt» A7 05 00`); hot-load proven (`runtime.ts load ../obj/mode_selftest.text.bin`
→ CRC-verified, jumped into RAM, payload `md_init` ran and returned its marker).
"Flash once, hot-load arbitrary features over BLE" works end-to-end.

## The mode payloads

Each `patches/mode_*.c` compiles to position-independent Thumb loaded over sid
`0x7b`. Notable ones:

| Mode | Purpose |
|------|---------|
| `mode_selftest.c` | ABI-aligned smoke test |
| `mode_screenshot.c` / `screenshot.c` | QOI framebuffer capture → sid `0x7d` |
| `mode_text.c` / `mode_boxtest.c` | 8×8 font ([`font8.h`](../../patches/font8.h)) text/box into the raw canvas |
| `mode_ownmode.c` / `mode_ownapp.c` | become the foreground app, render own full-screen page |
| `mode_ownanim.c` | onboard 3D stereo demo + L/R barrier sync + gyro head-tracking |
| `mode_sync.c` | cross-lens sync experiments |
| `mode_draw.c` / `mode_drawterm.c` | drawing / terminal rendering |
| `dbg_terminal.c` | streams internal terminal-mode FSM transitions over sid `0x7e` |

## Own-mode 3D stereo demo (`mode_ownanim.c`)

A self-controlled full-screen mode. Achieved (all HW-confirmed):

- Onboard wireframe **icosahedron** (12 verts, 30 edges, Q8 fixed-point
  rotation, `SINQ8` sin table, Bresenham lines, depth-fade).
- **L/R barrier sync** (delta ≤ 1; wait-for-ack peer protocol, both directions
  proven — see [04 — Two lenses & sync](04-two-lens-and-sync.md)).
- **True stereo parallax** (per-vertex eye-shift from `lens_side()`, not a flat
  sprite offset).
- **L-capture relay** (slave → master QOI fragment via `EVT_LCHUNK`).
- **IMU gyro** enabled via `FUN_00529c44` (config `{1,1,1}`, chip flags go
  `0x01 → 0x29` = accel + gyro_fused + quat); orientation floats become valid.
- 3×3 rotation matrix mode (Q14 fixed-point, differential update from gyro
  angular velocity, no gimbal lock); the master shares its matrix to the slave in
  an extended 23-byte SYNC (9× i16 Q12).

### IMU internals

- **Ring:** `*(u32*)0x4be79c` → SRAM ring. Header 12 B, 20 entries × 0x70 B; idx
  at `ring+8`.
- **Entry struct** (`imu_ring_entry_t`, 0x70 B): `+0x10` flags
  (b0=accel, b1=gyro_chip, b3=gyro_fused, b5=quat), `+0x12` accel_raw i16,
  `+0x18` gyro_chip_raw i16, `+0x1e` gyro_fused i16, `+0x24` quat q16, `+0x34`
  accel_cal float, `+0x40` gyro_chip_cal float, `+0x4c` gyro_fused_cal float,
  `+0x58` quat_filt float, `+0x68` orient float (axes swapped).
- **Gyro enable:** `FUN_00529c44(*(u32*)0x4bbeb8, mode, &cfg)`, `cfg={accel,gyro,mag}`;
  `mode=0` → chip reg 0x18, `mode=1` → reg 0x58. FW init enables accel only.

### Remaining issue

After enabling the gyro, the **IMU callback rate drops to ~1 Hz** (from the
normal ~5–20 Hz) — the register write changes the chip's sampling config, so the
model responds to head movement but with ~1 s latency. The orient values are
valid when they update; the problem is purely the rate. Fix path: RE
`DRV_IMUAccelConfig`'s rate parameter (accepts 100–5024 Hz) and set it alongside
the sensor-enable, or find the correct chip rate register.

## Feature roadmap (mode payloads)

debug, screenshot, differential + compressed display (mode3/9 + inflate), stereo,
animation-VM (send a program → on-device render), 3D wireframe (on-device
fixed-point project + line-draw), lazy-scroll-differential protocol
(viewport-aware, send only diffs, touchpad-slide driven).
