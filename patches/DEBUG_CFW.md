# Terminal-mode printf-debug CFW (`dbg_terminal.c`)

A build of the CFW that surfaces the **internal terminal-mode UI state machine**
over BLE so you can watch, on real hardware, exactly what the terminal UI FSM is
doing — and pin down why injected agent text never binds to the on-lens content
view.

It adds **three call-site hooks** and one small injected translation unit
(`dbg_terminal.c`). It emits two kinds of compact 14-byte binary records as
`aa21` frames on a **dedicated sid `0x7e`** that your external BLE client reads
with its raw-frame listener (`onRawFrame`). Nothing else in the firmware's
behavior changes.

---

## 1. Chosen mechanism and why (evidence-based)

**Chosen: an injected `dbg_emit()` that formats a fixed binary record and sends it
via the firmware's own aa21 send primitive `FUN_0047398c` on sid `0x7e`, driven
by three call-site `bl` redirects.**

The alternative the brief asked us to prefer *if viable* — force-enable the log
level gate `FUN_0043d072` and read the firmware's existing rich `terminal.ui` /
`terminal.pb` log strings over NUS — was investigated and **rejected on
evidence**:

- **`FUN_0043d072` returns a single *global* level byte, not a per-tag mask.**
  Disassembly (`ldr r0,[pc,#0x68]; ldrb r0,[r0]; bx lr`) shows it reads one global
  byte; log sites test individual bits of it (`lsls #0x1e/#0x1f/#0x1d`). There is
  no per-module ("terminal.ui" vs everything-else) granularity at this function,
  so forcing it to `0xFF` would enable **every log site in the whole firmware** —
  a firmware-wide flood, exactly the kind of behavior change that is risky on a
  device we intend to flash (log-formatting cost, possible watchdog/timing
  effects). *Verified by disassembly.*
- **The NUS log-routing is unverifiable offline.** `AT^NUS` / `NUS+OK\r\n` and a
  `log_output` string exist in the image (`at.core` AT-command table), but there
  is **no evidence in the static image that the `FUN_0043d514` formatted-log sink
  is routed onto the NUS characteristic**. We could not confirm the "enable NUS →
  logs stream over BLE" hypothesis without hardware. *Assumed-at-best; not proven.*
- By contrast, the send primitive path is **fully verifiable offline** and
  **minimal/targeted**:
  - `FUN_0047398c(type=1, sid, ptr, len)` is the exact primitive `settings_ext.c`
    already reuses; real callers set `r0=1` (72 call sites inspected). *Verified.*
  - It **self-gates on link-readiness** (calls a "can I send?" check first and
    returns error code `8`, sending nothing, if this lens isn't the transmitting
    side / BLE is down) — so calling it from any task/context is a safe no-op when
    it can't send. *Verified by disassembly.*
  - Only the **three terminal chokepoints** are touched, so there is no log flood.
  - The whole thing is validated in the Unicorn emulator against the actual
    compiled, patched bytes (see §6).

So the injected-`dbg_emit` route is both **lower risk** (targeted, self-gating,
no global logging change) and **higher confidence** (end-to-end validated
offline) than the NUS/force-enable route.

---

## 2. What it hooks (all length-preserving `bl` redirects)

Same idiom as `gesture_fwd.c` / `settings_ext.c`: replace one 4-byte `bl` with a
`bl` into an injected wrapper; the C ABI preserves callee-saved registers and the
wrapper tail-calls / re-invokes the real target. No prologue relocation, no
bootloader/flash logic touched. Byte offsets are file offsets (ghidra − 0x39E680).

| Stock site (ghidra) | Stock `bl` → | Redirected to | Wrapper |
|---|---|---|---|
| `0x5e5536` (UI-task dispatch) | `terminal_ui_fsm_handler` `0x5e8b00` | `dbg_fsm` | reads state, calls real handler, reads state, emits |
| `0x5e5500` (post-mode-switch `DISPLAY_ENTER(1,0)`) | `terminal_ui_fsm_handler` `0x5e8b00` | `dbg_fsm` | same wrapper (captures the first BOOTSTRAP→CLOSED) |
| `0x5e53d0` (enqueue inside `fire_ui_event` `0x5e535e`) | rtos `queue_send` `0x46435a` | `dbg_enqueue` | captures live state + posted event, tail-returns real result |

The `dbg_enqueue` hook redirects **only** `fire_ui_event`'s own call to the
generic queue-send; every other caller of `0x46435a` keeps its own `bl` and is
untouched. `dbg_enqueue` additionally **guards on `qid==0x30`** (the terminal UI
event queue) so it never disturbs any other queue traffic.

Injected function addresses in this build: `dbg_fsm` @ `0x0078fe3e`,
`dbg_enqueue` @ `0x0078fed0` (appended blob at MRAM `0x0078f188`, 371 KB under the
safe ceiling `0x007f0000`).

---

## 3. Record format (both records are exactly 14 bytes, little-endian)

Read them on **sid `0x7e`**. Every record starts with magic `0xE7`.

```
offset  size  field
  0      1    magic      = 0xE7
  1      1    rec_type   = 0x01 (FSM transition)  |  0x02 (event enqueued)
  2      1    state_a
  3      1    event_id
  4      1    state_b
  5      1    reserved   = 0x00
  6      4    arg        (u32 LE)  — the event's 32-bit argument
 10      4    tick_ms    (u32 LE)  — firmware monotonic ms tick at emit time
```

### rec_type `0x01` — FSM transition (emitted on the UI task, by `dbg_fsm`)
- `state_a` = **old_state** (before the dispatcher ran)
- `event_id` = the event just dispatched
- `state_b` = **new_state** (after the dispatcher ran)
- → this is the ground-truth **`old_state --event--> new_state`** transition.

### rec_type `0x02` — event enqueued (emitted on the posting task, by `dbg_enqueue`)
- `state_a` = **live fsm_state observed at the moment the event was posted**
- `event_id` = the event being enqueued to the UI queue
- `state_b` = `0xFF` (sentinel; unused for this record type)
- → this is the ground-truth **"who posted what, and what state they saw"**.

`tick_ms` on both records lets you **interleave the RX-task posts (type 2) with
the UI-task transitions (type 1) by time** — which is exactly how you observe the
RX/UI race that drops the content bind.

### Decode reference (from `RECONSTRUCTED_fsm.md` / `RECONSTRUCTED_ui_render.md`)

States (`state_a`/`state_b`): `0`=BOOTSTRAP `1`=CLOSED `2`=IDLE `3`=BLOCKED
`4`=VOICE_CAPTURING `5`=ASR_STREAMING `6`=ASR_FINAL `7`=AGENT_PROCESSING
`8`=AGENT_INTERRUPT_CONFIRM `9`=QUERY_PENDING `10`=QUERY_NOTIFICATION
`11`=SESSION_LIST `12`=NEW_SESSION_PENDING.

Key events (`event_id`): `1`=DISPLAY_ENTER · `0x0f`(15)=SESSION_STATUS_UPDATE ·
`0x10`(16)=AGENT_DONE · `0x11`(17)=AGENT_RESET · **`0x12`(18)=content
append/update** · **`0x13`(19)=content trigger / bind** · `0x23`(35)=SESSION_ID_CHANGED.

Example wire bytes (from emulator validation):
```
e7 01 02 0f 07 00  ef be ad de  e9 03 00 00
= magic, FSM, old=2(IDLE), ev=15(SESSION_STATUS_UPDATE), new=7(AGENT_PROCESSING), arg=0xdeadbeef, tick=1001
e7 02 07 13 ff 00  44 33 22 11  e9 03 00 00
= magic, FIRE, live=7(AGENT_PROCESSING), ev=0x13(content trigger), arg=0x11223344, tick=1001
```

---

## 4. How to read it from the external BLE client

1. Enter terminal mode and drive it exactly as you do today (protobuf on sid
   `0x30`).
2. Register your raw-frame listener and **filter for sid `0x7e`, magic byte
   `0xE7`**. Each frame's payload is one 14-byte record (parse per §3).
3. Both lenses run their own FSM; whichever lens is the transmitting side emits
   the frames. If you have separate BLE connections to left/right, the connection
   the frame arrives on tells you the lens (no side byte is needed in the record).

No handshake is required — the debug frames start flowing as soon as terminal
mode drives any FSM dispatch or event post. (You do **not** need `AT^NUS`.)

---

## 5. What to look for (mapping records → the questions we're debugging)

- **Every FSM transition** → read the `rec_type 0x01` stream:
  `old_state --event_id--> new_state`. e.g. confirm you actually reach and *hold*
  `7`(AGENT_PROCESSING), or catch it bouncing to `3`(BLOCKED)/`2`(IDLE).

- **`agent_content`'s observed state + did the content-bind fire?** →
  `agent_content` (RX) always posts `0x12`(18) (text append) and posts
  `0x13`(19) (content trigger / bind) **only when it observed `fsm_state==7` at RX
  time**. In the `rec_type 0x02` stream:
  - a `0x13` FIRE record ⇒ **content-bind fired**, and `state_a` shows the state it
    saw (must be `7`).
  - a `0x12` FIRE record with **no** matching `0x13` right after ⇒ **bind dropped**;
    `state_a` shows the (non-7) state `agent_content` actually observed — i.e. the
    RX/UI race or a wrong state, made visible.

- **`session_status` gate outcome** → `session_status` (RX) posts `0x0f`(15)
  when `status==1` matches the current session (else `0x10`/`0x11` for done/reset).
  Then the `rec_type 0x01` stream shows whether the UI handler actually advanced
  (`2 --15--> 7`) or **stayed put** (`2 --15--> 2`), which is the stale/mismatched
  -session drop. Compare the `arg` (session id) across FIRE and FSM records and
  against your wire ids.

- **The race, directly** → sort both record types by `tick_ms`. You will see
  whether the UI task had applied `session_status`'s `IDLE→7` transition (type 1)
  *before* `agent_content`'s RX handler read the live state and posted (type 2).
  If the FIRE `0x12` posts show `state_a` still `2`(IDLE) while the `2 --15--> 7`
  FSM transition arrives later, that is Scenario C from `RECONSTRUCTED_ui_render.md`
  reproduced on real hardware.

---

## 6. Verified vs assumed

**Verified (by disassembly and/or Unicorn emulation of the actual patched bytes):**
- Exact stock bytes at all three hook sites, and that the CFW redirects them to
  `dbg_fsm`/`dbg_enqueue` while leaving surrounding instructions byte-identical.
- The send primitive convention `FUN_0047398c(type=1, sid, ptr, len)` and that it
  self-gates on link-readiness (safe no-op off-side).
- The FSM ctx pointer (`0x5e8d98` → `0x2006e0b0`) and state byte offset `+0x275`.
- `dbg_fsm` reads old_state, calls the **real** `terminal_ui_fsm_handler`, reads
  new_state, and emits the `{old,event,new,arg,tick}` record on sid `0x7e`.
- `dbg_enqueue` captures `{live_state,event,arg,tick}`, guards on `qid==0x30`, and
  **tail-returns the real queue-send result** (so `fire_ui_event`'s own return is
  preserved). Non-`0x30` queues emit nothing and still forward.
- Image checksums (component CRC32C + preamble CRC32) are correct:
  `g2flash.py --recompute-checksums` reports "already consistent, no changes".

**Assumed / not proven on hardware (call out before trusting):**
- That sid `0x7e` frames are forwarded end-to-end to your phone client exactly
  like other outbound `aa21` frames. (Highly likely — `onRawFrame` sees all
  frames and `0x7e` is otherwise unused — but not hardware-confirmed here.)
- `tick_ms` is the firmware's monotonic ms tick (`FUN_00448138`); its absolute
  epoch is irrelevant — only deltas/ordering matter.
- The state/event *name* legend in §3 carries the confidence levels documented in
  `RECONSTRUCTED_fsm.md` (numeric ids are exact; some names are HIGH/MODERATE).

---

## 7. Build (BUILD ONLY — do not flash from this doc)

clang thumbv7em cross-compile **is available** in this environment, so the normal
regenerate-then-build path works:

```bash
cd /Users/mojashi/repos/odd/g2flash

# 1) regenerate the committed patch set from the C sources (needs clang)
python3 patches/gen_patches.py g2_2.2.4.34.bin patches/cfw_patches.json
#   (equivalently: ./build_cfw.sh --update-patches)

# 2) apply the committed patch set to produce the image (no compiler needed)
python3 patches/apply_patches.py g2_2.2.4.34.bin patches/cfw_patches.json g2_2.2.4.34_cfw.bin

# 3) (optional) confirm checksums are already consistent
python3 g2flash.py --recompute-checksums g2_2.2.4.34_cfw.bin
```

Or the one-shot (regenerates with clang if present, then applies + verifies the
pinned hash):

```bash
./build_cfw.sh --update-patches      # regenerate committed JSON from sources, then build
# or just:  ./build_cfw.sh           # apply committed JSON (already regenerated) + verify
```

- **New output SHA-256:** `66f205100e6c709a03f8dc606569778fb14cc4cb0b1a18273a3a402f939edf45`
  (was `4d5f26f8804bc5d7fdd1d0513739c1a17a9c5a4108221811a1346fd1e148c97e` for the
  image-features-only set). `build_cfw.sh`'s pinned `OUT_SHA256` has been updated
  to the new value.
- Base (stock) SHA-256 is unchanged:
  `f9a93621a7141e0ae54ca6371cd2f1b4afbffa61f302ace096e0656ba25b1754`.

**Flashing readiness:** the image is built and self-consistent, but **it has NOT
been flashed** — flashing is the user's call (it can brick the device). When you
choose to flash, use the normal `g2flash.py` path from the README.
