# 04 — Two lenses & cross-lens sync

The two G2 lenses are **independent Apollo510 MCUs linked by a BLE master/slave
connection** (Cordio stack: `[ble.master]` / `[app_slave]` / `[ble.comm]`).

- **R lens = MASTER = the "transmit lens"** (`FW_SIDE() == 1`, `0x45a8ec`),
  connected to the phone.
- **L lens = SLAVE.** Apps branch on `MASTER_ROLE` / `SLAVE_ROLE`.
- The loader's `api_send` / reply gate on `FW_SIDE == 1`, so **only R sends back
  to the phone** — you cannot BLE-capture the L lens directly (triggering a
  screenshot on the L arm still returns the R lens's frame unless you relay via
  the peer link, below).

## Arm routing (HW-proven)

g2-kit connects to two distinct BLE devices (`Even G2_..._L_...` vs
`Even G2_..._R_...`, same service UUID). A runtime write (sid `0x7b`) to the
**L device is executed by the L lens locally *and* relayed to R**:

- **`arm:"L"` reaches BOTH lenses** (L runs it, R gets it relayed → SIDE:2 on L
  + SIDE:1 on R, each its own instance).
- **`arm:"R"` reaches only R.**
- **Never load via both arms.** `arm:"R"` loads R, then `arm:"L"` re-loads R
  (LOAD_FRAG idx0 frees R's live code buffer while active → hardfault). This was
  the cause of every "R died / load-both breaks" symptom.
- **To run on both lenses: use `arm:"L"` only.** Reads still disambiguate by
  side gating (`'k'` → R replies its frame; `'l'` → L's instance relays its
  frame via peer → R).

## Inter-lens messaging (the "transmit mechanism")

Sits in the **`sync.module.api`** at `0x463e00`–`0x465800`, right after the
app-command poster `post_app_command` (`FUN_00463f1a`):

- **`send_data_to_peer` = `FUN_00464c28`**, signature
  `send_data_to_peer(u16 appID, void* data, uint len, u32 arg4, uint eventType)`
  — sends arbitrary bytes to the peer. Used by `evenhub_uiCb`
  (`FUN_00464c28(0xe0,&d,1,0,5)`) and the gesture relay
  (`FUN_00464c28(0x10d,buf,0x30,0,5)`).
- **`send_input_event_to_peers` = `FUN_00464ef0`** — builds a `{cmd=3,sub=7,...}`
  message and posts it to the peer queue.
- Peer data is delivered on the receiving lens to the target app's **`dataCb`**
  (event-3 / PEER path).

**Bidirectional, HW-confirmed:** [`docs/peer_comms_map.md`](../peer_comms_map.md)
describes this as a "master-only listener" for the internal
`sched_recv_peer_sync_data` consumer, but a custom app's `dataCb` receives peer
data in **either direction** — the barrier below sends type-4 `EVT_SYNC`
master→slave *and* `EVT_ACK` slave→master through this same primitive, both
verified working. The "master-only" restriction is specific to the internal
system consumer, not to app-registered `dataCb` delivery.

> **Correction (flagged during RE):** `anim_gate_sync_tick` (`0x572648`,
> `even_ai.animation` tag) was earlier described as "the native L/R animation
> gate-barrier," but a re-check found **0 references of any kind** to its address
> anywhere in the app image (direct call, movw/movt, or literal-pool word). Treat
> it as unproven / possibly dead code until a real caller is found.

## Native cross-lens sync

**The native L/R sync = every stock app runs on both lenses (flashed), and R
forwards its app-level events / commands / display-reflashes to the peer; L's
copy renders identically.** This is **not** image transfer — text boxes, lists,
and list scroll all sync this way. Confirmed by xref: `send_peer_app_cmd_op3`
(`0x46435a`) has **120 call sites** across ~40 functions (navigation, dashboard,
health, quicklist, menu, evenhub, every `*InputEventHandler`);
`send_input_event_to_peers` is called by `menu_inject_event` ×9 (that is how list
scroll syncs to both eyes); `AsyncRequestDisplayReflash` (`0x45ae4e`) by
navigation / dashboard / evenhub.

The reflash-forward chain (image path, but the primitive is generic):

1. On the **R** lens, a completed message calls the emitter
   `evenhub_common_device_private_event_cmd` (`0x4ff44a`), which calls either
   `AsyncRequestDisplayReflash(0xe0,data,len,token=300)` or
   `send_peer_app_cmd_op3(0xe0,...)`.
2. `AsyncRequestDisplayReflash(id,data,len,token)` = `0x45ae4e` prepends `token`
   as a 4-byte header and submits work onto the framework queue.
3. Worker `_AsyncReflashApplicationDataHandlerCb` = `0x45ad6a`:
   (a) `FUN_00453a80(token)` = an RTOS scheduler/timer primitive (inserts into
   the time-ordered timer queue by `token`, then pends PendSV — it **schedules /
   kicks**, the actual reflash is done by the display thread it wakes);
   (b) `send_peer_app_cmd_op3(id, data+1, len-4, 0)` **forwards the same reflash
   to the peer lens** — this forward is the cross-lens part.
4. The peer (L) receives the app command → runs the same reflash for the same
   token → both lenses present together.

Note `list scroll` sync uses the lighter `menu_inject_event` →
`send_input_event_to_peers` path: it forwards the triggering **input event**, and
each lens replays it through its own deterministic local LVGL scroll physics
(`xQueueSend` into the local input queue, no render call). That syncs the *start*
of a bounded animation, not every frame.

## Why own-mode desyncs, and how to fix it

`mode_ownanim` draws into its own `lv_image` buffer and calls
`lv_obj_invalidate` (`0x4405f6`) → each lens's own LVGL refr timer, which each
lens runs independently → they drift ("numbers differ L/R, drift grows").

Three working routes to synced custom L/R content:

1. **Own-mode on both + a self-built peer wait-for-ack barrier** — done, ≤1
   frame, high fps (below).
2. Hijack a stock dual-lens app (terminal / image mode-4).
3. Native reflash-forward as a two-phase prepare-then-flip, for delta→0 (both
   flip the same instant vs the barrier's ≤1-frame lead) — but ≤1 frame (~16 ms)
   is already below fusion perception, so only needed if a stereo artifact shows.

### The wait-for-ack barrier (implemented, HW-proven)

In [`patches/mode_ownanim.c`](../../patches/mode_ownanim.c), via
`send_data_to_peer`:

- MASTER (side 1) draws frame N + sends `EVT_SYNC(N)=0x41` to the peer, sets
  `waiting`; does **not** advance.
- SLAVE (side 2) on `EVT_SYNC` renders exactly N (draw + invalidate in RX ctx —
  safe, invalidate only marks dirty) then sends `EVT_ACK(N)=0x42`.
- MASTER on `EVT_ACK` does `frame++`, clears `waiting` → next tick draws + sends
  N+1.

So the master is throttled to one in-flight frame (BLE RTT), both show the same
N, zero accumulation. Guards: master `SYNC_TIMEOUT_MS(200)` advances on a lost
ack (no stall); slave `SYNC_IDLE_MS(600)` resumes self-tick if the master goes
quiet; the clean master-draws-in-tick / slave-draws-in-RX split avoids a buffer
race. Enable via `'m'` sent to R (slave auto-enters on the first `EVT_SYNC`);
`'n'` disables. Baseline delta drifted −2 → −4 and growing; the barrier collapsed
it to **≤1 frame and held it stable** (`demos/barrier-L.ts`, HW-confirmed).

## Capturing the L (slave) lens

Implemented in [`patches/screenshot.c`](../../patches/screenshot.c) +
`mode_ownanim`: the fragment emitter routes through a compile-time
`SS_SEND_HOOK`. On R (side 1) it sends straight to the phone on sid `0x7d`; on L
(side 2) it calls `send_data_to_peer(OUR_APPID, frag, len, 0, EVT_LCHUNK=0x43)`
→ R receives `EVT_LCHUNK` in our `dataCb` and re-emits it verbatim on sid `0x7d`,
so the host's existing screenshot receiver reassembles the L image transparently.
Trigger with the `'s'` command targeted at L (runtime `ARM=L`); capture one lens
at a time. Capture source on L = `SS_FB_L8` (`0x200745cc` draw buf) = the
composited L panel. Watch peer payload size (frags ≤ 200 B) and peer-queue flood.
