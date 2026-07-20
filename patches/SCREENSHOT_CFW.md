# On-demand screenshot CFW (`screenshot.c`)

A superset of the debug/display CFW that adds an **on-lens screenshot** feature: on
request from the phone, the firmware reads the **real panel framebuffer** (whatever is
actually on the lens — terminal text, dashboard, menus), compresses it with a
single-pass **grayscale QOI** codec, and streams it back over BLE as a sequence of
`aa21` frames on a dedicated **sid `0x7d`**. A macOS/bun client (`demos/screenshot.ts`)
requests the capture, reassembles + verifies the fragments, QOI-decodes, and writes a
PNG (+ PGM).

It is added *alongside* `dbg_terminal.c` and the image/display glue (`zlib_glue.c`) — one
image contains all of them. Nothing else in the firmware's behavior changes.

---

## 1. The framebuffer we capture (evidence)

The G2 renders its UI with **LVGL v9.3 on an Ambiq Apollo510 (NemaGFX GPU)** and drives a
**JBD4010 microLED** panel over QSPI. The display pipeline has two full-screen buffers:

```
 LVGL widgets/text/menus ──render──▶  L8 draw buffer (576×288, 8bpp)
     (RENDER_MODE_DIRECT, single-buffered)        │  *(*(u32*)0x200745cc + 0x10)
                                                   ▼  displaydrvmgr packs 576×288 → 4bpp
                                        ┌──────────────────────────────────────┐
                                        │ PANEL CANVAS  *(u32*)0x20074464       │  ◀── WE CAPTURE THIS
                                        │ 640×480, 4bpp (A4), stride 320 B      │
                                        │ 576×288 UI composited at ~(32,96)     │
                                        └──────────────────────────────────────┘
                                                   │  JBD4010 QSPI DMA (cmd 0x62)
                                                   ▼
                                              microLED panel
```

**We capture the panel canvas `*(0x20074464)` — the exact buffer the JBD4010 QSPI DMA
scans out, i.e. what the wearer physically sees.** CONFIRMED by disassembling the panel
driver's `PartialReflash` (`FUN_00589290`) and `FullReflash` (`FUN_005893c6`):

```
005892c2  mov.w r1, #0x280        ; 640
005892c6  mul   r1, r1, r5        ; 640 * row
005892cc  sdiv  r1, r1, #2        ; /2  →  stride = 0x140 = 320 B/row   ⇒ 4bpp, 640 wide
005892d0  ldr.w r2, [pc, #0x564]  ; literal @0x589838 = 0x20074464   (driver canvas global)
005892d4  ldr   r2, [r2]          ; r2 = *(0x20074464) = CANVAS BASE
005892d6  add   r1, r2            ; canvas + 320*row
005892d8  add.w r8, r1, r0        ; + (x>>1)
0058933e  movs  r1, #0x62         ; QSPI row-stream command 0x62
```

The address space is clamped to **640×480** (`cmp x2,#0x27f` / `cmp y2,#0x1df`). The
`0x20074464` global is set by `jbd4010_init` (`FUN_00588c6e: str r1,[0x20074464]`), which
the display manager dispatches (`FUN_004d4d7e`) with the same canvas pointer it also
caches at `0x200007b8` — so `*(0x20074464) == *(0x200007b8)`. We use the driver-side
global `0x20074464` (closest to the actual panel read).

- **Format**: 4bpp packed, **2 pixels/byte, high nibble = even/left pixel** (LIKELY→
  CONFIRMED: the canvas writer at `0x004d52e2` does `ands r2,#0xf0` to keep the high
  nibble for even x — same convention as `zlib_glue.c`'s `unpack4bpp`). Nibble `n` →
  gray `n*17` (0..255), the display's native 16-level depth.
- **Geometry**: 640×480, stride 320 B, tightly packed = 153600 B. The 576×288 UI sits
  inside at offset ~(32,96) `((640-576)/2, (480-288)/2)`; the cleared border shows as a
  black margin in the PNG. Capturing the whole 640×480 needs no offset assumption and is
  exactly the physical panel image.

**Confidence.** The scan-out source (`*(0x20074464)`), stride 320, and 640×480 geometry
are **CONFIRMED** from the reflash disassembly. The panel is truly refreshed from this
buffer. What is **ASSUMED / hardware-only**: (a) the exact nibble order (high=even is
strongly supported but not run on hardware); (b) that reading the canvas mid-refresh
won't tear (single Cortex-M55 core, CPU-coherent; the driver dcache-cleans before DMA, so
a CPU read sees the same bytes — but a capture that races an in-progress L8→A4 repack
could catch a partial frame; for a static screen it is stable).

**Alternative (`-DSS_FB_L8`).** The LVGL L8 render target one stage upstream —
`*(*(u32*)0x200745cc + 0x10)`, 576×288, 8bpp — is provided as a compile option (richer
gray, no border, but not the literal panel feed). The default is the panel canvas.

---

## 2. Trigger + hook (universal, any UI)

Every inbound sid-routed app frame from the phone passes through a single service
dispatcher call. We redirect it:

| Field | Value |
|---|---|
| Hook `bl` (ghidra) | **`0x0045aaa4`** |
| Stock 4 bytes | **`e7 f7 e0 f8`** (`bl 0x00441c68`) |
| Original target | `FUN_00441c68` service dispatcher (called `bl 0x00441c69` from the wrapper) |
| Redirected to | `cap_rx_hook` (appended blob) |

`cap_rx_hook(r0=sid, r1=payload, r2=len, r3=subcode)` — the 4 values are already in the
ABI arg registers at the call site (verified: `0045aaa2 movs r1,r4 (payload); 0045aaa4
bl`). It fires a capture when the frame is a request on the **otherwise-unused serviceID
`0x7d`** (confirmed absent from the 41-entry service table at `0x006a6cc4`), then
**tail-calls the real dispatcher** so all normal traffic — and the unknown sid 0x7d, which
the dispatcher cleanly logs-and-frees — behaves byte-for-byte as stock.

```c
int cap_rx_hook(uint32_t sid, uint8_t *payload, uint32_t len, uint32_t subcode) {
    if (sid == 0x7d && payload && len >= 1 && payload[0] == 0xC7)  // 0xC7 = "capture"
        cfw_screenshot_run();     // gates FW_SIDE()==1, resolves the live FB, streams
    return FW_DISPATCH(sid, payload, len, subcode);
}
```

`cfw_screenshot_run()` runs only on the **transmitting lens** (`FW_SIDE()==1`, right); the
send primitive `FUN_0047398c` self-gates on the other lens, so sending the trigger to both
lenses is harmless (the left copy no-ops).

**Context / watchdog (hardware-unverified).** The capture+send runs **inline** on the
sync-framework thread-pool worker task — a full task context (not an ISR) that already
runs the heavyweight dispatch chain. `FUN_0047398c` self-paces on link readiness. A
typical monochrome UI (mostly-black border + text) compresses to a handful of fragments;
an adversarial full-detail frame is a few hundred `aa21` sends. If a watchdog or the ESS
TX queue proves too tight on real hardware, split the work: set a RAM flag in
`cap_rx_hook` and drain it from a periodic display hook (the `bl` site is a one-line
change). This is called out because it is the one timing behavior that cannot be
measured offline.

---

## 3. Wire protocol

### 3.1 Fragment (one `aa21` frame on sid `0x7d`, ≤ 200 B ≤ ~232 aa21 cap)

```
offset size field
  0     1    magic       = 0xA5
  1     1    version     = 0x01
  2     2    frag_index  u16 LE (0-based)
  4     1    flags       bit0 = LAST fragment
  5     1    reserved    = 0
  6     2    payload_len u16 LE (≤ 192)
  8     ..   payload
```

### 3.2 Reassembled blob (payloads concatenated in index order)

```
  0     4    "G2SS"
  4     1    version = 1
  5     1    flags   bit0 = up-filter applied (0 by default)
  6     2    width   u16 LE   (640)
  8     2    height  u16 LE   (480)
 10     ..   QOI grayscale stream (qoi_len bytes)
 -8     4    qoi_len u32 LE   (trailer)
 -4     4    crc32   u32 LE   (zlib/PNG CRC-32, poly 0xEDB88320, of the QOI stream only)
```

The client verifies `qoi_len` and `crc32`, reports any missing fragment indices, and
times out (idle 4 s / overall 20 s).

### 3.3 Grayscale QOI variant (1 channel)

Single-pass, no malloc, ~0.5 KB stack scratch. State: `prev` (init 0), 64-entry running
`index` (init 0). Ops (first byte):

| Byte | Op | Meaning |
|---|---|---|
| `0x00..0x3F` | INDEX | `v = index[b & 0x3F]` |
| `0x40..0x7F` | DIFF | `v = (prev + ((b&0x3F) - 32)) & 0xFF`  (delta −32..+31) |
| `0xC0..0xFD` | RUN | repeat `prev`, `(b&0x3F)+1` times (1..62) |
| `0xFE` | GRAY | literal: next byte is the raw gray value |
| `0x80..0xBF`, `0xFF` | — | unused (never emitted) |

`index` updates on DIFF/GRAY only; `prev` on INDEX/DIFF/GRAY. `HASH(v) = (v*15)&63`.
An optional PNG-style **up filter** (subtract previous row) is behind `-DSS_UP_FILTER`,
**off by default** (horizontal RUN already handles the large flat regions; the client
reverses it automatically when the blob flag is set). A 4bpp source (the panel canvas) is
unpacked to 8bpp gray (`nibble*17`) before encoding.

---

## 4. Taking a screenshot

```bash
cd g2flash/demos
bun screenshot.ts [out_basename]      # default: g2shot-<timestamp>
```

The client connects, sends the capture request on sid `0x7d` (opcode `0xC7`) to the right
arm, collects the sid-`0x7d` fragments (`onRawFrame`), reassembles + verifies them,
QOI-decodes to a 640×480 grayscale raster, and writes `<basename>.png` and `.pgm`. It
prints the saved path and dimensions. The 576×288 UI appears centered inside the 640×480
panel image (black margin around it).

---

## 5. Build (BUILD ONLY — do not flash from this doc)

```bash
cd g2flash
python3 patches/gen_patches.py g2_2.2.4.34.bin patches/cfw_patches.json   # clang: regenerate patch set
python3 patches/apply_patches.py g2_2.2.4.34.bin patches/cfw_patches.json g2_2.2.4.34_cfw.bin
python3 g2flash.py --recompute-checksums g2_2.2.4.34_cfw.bin              # "already consistent, no changes"
# one-shot equivalent:  ./build_cfw.sh --update-patches   (then ./build_cfw.sh)
```

- **New OUT_SHA256:** `1a1b82fd224d9190e79a3be808835c19b400e1199d453af8f4e563636e5b7dcf`
  (was `66f205100e6c709a03f8dc606569778fb14cc4cb0b1a18273a3a402f939edf45` for the debug
  CFW). `build_cfw.sh`'s pinned hash has been updated.
- Base (stock) SHA-256 unchanged: `f9a93621a7141e0ae54ca6371cd2f1b4afbffa61f302ace096e0656ba25b1754`.
- Combined injected blob: 17578 B at MRAM `0x0078f188`..`0x00793632` — **370 KB under**
  the safe ceiling `0x007f0000`. Bootloader untouched; 24 patches total (23 debug/display
  + 1 screenshot hook); every in-place edit is length-preserving.

**Flashing is NOT done here** (it can brick the device). Use the normal `g2flash.py` path
when you choose to flash.

---

## 6. Verified vs assumed

**Verified (disassembly and/or Unicorn emulation of the actual compiled patched bytes):**
- Panel scan-out source `*(0x20074464)`, stride 320, 640×480, 4bpp (reflash disasm §1).
- Hook site `0x0045aaa4` stock bytes `e7 f7 e0 f8` = `bl 0x00441c68`; the ABI
  `(sid, payload, len, subcode)` in r0..r3; sid `0x7d` absent from the service table.
- The **compiled** `cfw_screenshot_capture` / `cfw_screenshot_run` / `cap_rx_hook` bytes:
  loaded into the emulator, they read a planted framebuffer, emit sid-0x7d fragments, and
  the client decoder reconstructs the **exact** test pattern with CRC + dims verified
  (8bpp and 4bpp inputs, flat/random/UI patterns, and the full 640×480 `*(0x20074464)`
  path). `cap_rx_hook` captures only on sid 0x7d + opcode 0xC7; other sids/opcodes forward
  to the dispatcher without capturing.
- The patched image is **byte-identical** to stock except the 88 recorded in-place bytes
  and the tail append; the hook decodes stock `bl 0x441c68` → cfw `bl` into the appended
  blob; the 4 non-main components (incl. the bootloader path) are unchanged; checksums are
  consistent.
- CRC-32 in the CFW matches Python `zlib.crc32` and the client's table CRC (poly
  `0xEDB88320`).

**Assumed / hardware-only (call out before trusting):**
- Nibble order high=even (strongly supported by the canvas-writer disasm, not run on hw).
- No tearing when the capture races an in-progress panel repack (fine for a static screen;
  a moving screen may catch a partial frame).
- Watchdog / ESS-TX-queue headroom for a long inline multi-fragment send (see §2); the
  client already reports missing fragments if any are dropped.
- That sid-`0x7d` frames are forwarded phone↔glasses like other `aa21` frames (highly
  likely — `0x7d` is otherwise unused and `onRawFrame` sees all frames — but not
  hardware-confirmed here). The unused-sid trigger has a documented fallback (match a
  magic prefix on an always-accepted sid) if hardware drops unknown serviceIDs pre-dispatch.
```
