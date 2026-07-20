# G2 inter-lens (peer) comms — RE map (2026-07-19)

**CORRECTION (2026-07-19, traced sched_exec_display_startup @0x45c3dc):** the "reconstructed synchronized-present
protocol" below (DispStartBlockingEn/Cancel gating the reflash/present) is WRONG. Traced the actual consumer of
the gate flag (`*0x0045c378` -> real flag at RAM `0x20074e1c`): only the **opcode==1** dispatch branch
(`AsyncRequestDisplayStartUp`/`request_display_startup`, i.e. INITIAL APP LAUNCH) checks this flag and defers if
set. The **opcode==3** branch (`send_peer_app_cmd_op3`, reflash/present — at 0x45d01e) does NOT check it at all;
it unconditionally queues the reflash message (`FUN_00448b0e`, 2000ms timeout). So `DispStartBlockingEn/Cancel`
synchronizes which APP both lenses have OPEN, not per-frame PRESENT timing — it is NOT usable for a delta->0
present barrier. The app-level wait-for-ack barrier (mode_ownanim.c, delta<=1, HW-proven) remains the best known
sync; no native "both eyes flip the exact instant" primitive was found for an ongoing animation.

**CORRECTION 2 (2026-07-19, HW-empirical):** the table below says "type-4 listener is master-only" (RX=
`sched_recv_peer_sync_data`), implying `send_data_to_peer` only delivers L→R. Our custom app's barrier
(mode_ownanim.c) empirically sends type-4 messages **in BOTH directions to our own registered appID's dataCb**
(EVT_SYNC master→slave AND EVT_ACK slave→master) and **both arrived correctly** (HW-proven: delta stayed ≤1,
and the L-capture relay — also type-4, slave→master — worked, capturing a verified SIDE:2 image). So the
"master-only" restriction found in `sched_recv_peer_sync_data` is NOT a restriction on type-4 delivery to an
**app-registered dataCb** in general — it's specific to that one internal system consumer (whatever
`sched_recv_peer_sync_data` is privately used for). For a custom app, `send_data_to_peer` (type4/op0xc) works
bidirectionally to your own appID's dataCb — this is the simplest, HW-confirmed choice for both directions,
not just L→R as the table implies.

## Send primitives & command space

I have the complete picture. Here is the analysis.

---

# G2 fw 2.2.4.34 — Inter‑Lens SEND primitives & peer command space

Analysis of `peer_bundle.txt` (54 fns). All wire‑format claims are read directly from the byte‑store sequences in the decompiled poster functions. Where the bundle truncates a function body (the dispatch/enqueue tail is cut on several), I say so explicitly rather than guess.

---

### 1. The common wire format — one 8‑byte peer header

Every app/data poster (`post_app_command` @ 0x463f1a, `send_app_command_to_peer` @ 0x4644c4, `SendDataToBothExt` @ 0x46471e, `send_data_to_peer[_noevent]` @ 0x464c28 / 0x464988) builds the **same 8‑byte header + payload** in the `len+8` buffer (`local_24[2]`). Reading the byte stores in `post_app_command` (lines 1436‑1445):

| off | field | source | notes |
|----|-------|--------|-------|
| `[0]` | **msgType** (u8) | `post_app_command` arg6 | = the **TinyFrame type / route** (0‑5). Called "sub/flags" in your prompt's `(3,2,0)`; it is the `2`. |
| `[1]` | **opcode** (u8) | arg5 | RX dispatch key. Listeners branch on `*payload >> 8` = this byte. The `op3`/`op16` in the fn names = this. |
| `[2..3]` | **appID / msg_id** (u16 LE) | arg1 | service / channel id (0x10, 0x1f, 0x105, 0x10c, …) |
| `[4..5]` | **eventType / flags** (u16 LE) | arg7 | delivered to RX handler as the "flags"; `_noevent` forces 0 |
| `[6..7]` | **payloadLen** (u16 LE) | arg3 | body length (capped, see below) |
| `[8..]` | **payload** | arg2, `fw_memcpy` | copied only if `len!=0 && data!=0` |

**RX side confirms the layout exactly.** `UserDataReplyListener` @ 0x45b90c: `puVar2 = *(ushort**)(msg+1)`; checks `*puVar2 >> 8 == 9` (opcode 9); `id = puVar2[1]` (off 2); `SendUserDataToThreadPool(id, puVar2+4 /*off 8*/, puVar2[3] /*off 6 len*/, puVar2[2] /*off 4 flags*/)`. Same shape in `sched_recv_peer_sync_data` @ 0x45ba68 (`>>8 == 0xc`) and `SlaveInputEventReplyListener` @ 0x45bbd4 (`>>8 == 7`).

So the effective addressing is **4‑level**: `msgType`→TinyFrame type→which lens's listener; `opcode`→listener dispatch; `appID`→service; and by convention **payload `[8]` = a service sub‑command** (onboarding 0xd/0xe/9, dashboard 3, charger 8/6/4, audio 1‑4).

### 2. The 12‑byte TX descriptor (queue element)

Before the header buffer, every poster allocs a 12‑byte descriptor via `sync_alloc_retry(0xc)`:

| off | field | set by |
|----|-------|--------|
| `+0` | `ctx` (reply/callback token) | `*local_24 = ctx` |
| `+4` | **type** (u16) = `msgType` | `*(u16*)(local_24+1) = msgType` (set **inside `if lens_side()==1`** in `post_app_command`/`send_input_event_to_peers`) |
| `+6` | `totalLen` (u16) = `len+8` | |
| `+8` | `payloadPtr` | `local_24[2]` |

`SyncModuleSendDataHandler` @ 0x45e9e8 dequeues these, reads `uVar1 = *(u16*)(local_24+1)` (the type at +4), and switch‑selects a `(uVar5,uVar6)` TinyFrame endpoint pair per type (lines 1237‑1241): type 0→`DAT_0045ef6c/70`, 1→`ef58/5c`, 2→`ef74/78`, 3→`ef84/88`, 4→`ef7c/80`; **type > 4 is rejected and the buffer freed**. It then calls `FUN_004a8286(*DAT_0045ef60, ctx24, uVar5, uVar6, 0x32)` (TinyFrame send, 0x32=50 retry/timeout) with a 24‑byte listener/reply context (`FUN_00486d14`+`FUN_0045a8dc`).

### 3. `post_app_command` — full signature & the trailing ints

```c
int post_app_command(ushort appID, void *data, ushort len, void *ctx,
                     byte opcode, byte msgType, ushort eventType);   // @0x463f1a
```
- Guard: `*DAT_00464968 != 0` (app‑command transport initialized) else return **‑1**.
- **Length cap: `len < 0x2801`** → max payload **0x2800 = 10240 bytes** (relevant for screenshots — chunk above this).
- Trailing ints `(opcode, msgType, eventType)` land on the wire as `[1]=opcode, [0]=msgType, [4..5]=eventType`. Your prompt's `(3,2,0)` = `opcode=3, msgType=2 (TF type 2), eventType=0`.
- `lens_side()=='\x01'` (master/R) branch sets descriptor type and (tail truncated in bundle) enqueues; the slave path is **cut off in the dump** — I can't see whether slave posts differ. Flagging as uncertain.

**Every distinct `(opcode, msgType, eventType)` tuple among visible `post_app_command` callers:**

| caller | addr | call | wire (type,op) | meaning |
|--------|------|------|----------------|---------|
| `request_display_startup` | 0x4642d6 | `(…,1,2,0)` | (2, **1**) | app **start‑up / display** on peer |
| `send_peer_app_cmd_op3` | 0x46435a | `(…,3,2,0)` | (2, **3**) | app **reflash / present** on peer |
| `evenhub_open` | 0x4643de | `(…,5,2,0)` | (2, **5**) | evenhub open |
| `send_peer_app_ctrl_op16` | 0x464462 | `(0,0,0,handle,0x10,2,0)` | (2, **0x10**) | app **ctrl** (no payload, handle=ctx) |

All four use **msgType=2** ⇒ TF **type 2**, which is registered **only on the slave** (see §5) ⇒ these are strictly **master R → slave L app commands**.

### 4. The full peer‑send primitive table

| primitive | addr | module | signature | wire `[0]`type / `[1]`op | fixed body | gate global | direction / when |
|-----------|------|--------|-----------|--------------------------|-----------|-------------|------------------|
| `post_app_command` | 0x463f1a | — | `(appID,data,len,ctx,op,mType,evt)` | caller‑set | generic 8B hdr+data, ≤10240 | `DAT_00464968` | core poster; you rarely call directly |
| `request_display_startup` | 0x4642d6 | — | `(appID,data,len,ctx)` | 2 / 1 | — | ″ | R→L: bring app up / initial display on the other eye |
| **`send_peer_app_cmd_op3`** | 0x46435a | — | `(appID,data,len,ctx)` | **2 / 3** | — | ″ | **R→L: trigger peer app "reflash"/present** — this is the display‑sync path (see §6b) |
| `evenhub_open` | 0x4643de | — | `(appID,data,len,ctx)` | 2 / 5 | — | ″ | R→L: open evenhub app |
| `send_peer_app_ctrl_op16` | 0x464462 | — | `(handle,a2,a3,a4)`→`(0,0,0,handle,0x10,2,0)` | 2 / 0x10 | empty body | ″ | R→L: app control, payload‑less |
| `send_app_command_to_peer` | 0x4644c4 | — | `(appID,data,len,ctx)` | **1 / 9** | hdr evt=0 | `DAT_00464968` | **type‑1 = bidirectional user‑data** (both lenses listen); RX=`UserDataReplyListener`→`SendUserDataToThreadPool`. Use for arbitrary app payloads that must reach the peer app's data handler. |
| `SendDataToBothExt` | 0x46471e | tFx | `(msg_id,data,len,ctx,sub_id)` | **1 / 9** | evt=**sub_id** | `DAT_00464968` | same type‑1/op‑9 as above but exposes the eventType field as `sub_id`; "ToBoth" ⇒ broadcast‑style. Use when you need a sub‑id/tag alongside the payload. |
| `send_data_to_peer` | 0x464c28 | — | `(app_id,data,len,ctx,event_type)` | **4 / 0xc** | evt=event_type | `DAT_004654fc` | type‑4 listener is **master‑only** ⇒ **L→R data**. RX=`sched_recv_peer_sync_data`. event_type delivered as flags. |
| `send_data_to_peer_noevent` | 0x464988 | — | `(msg_id,data,len,ctx)` | **4 / 0xc** | evt=**0** | `DAT_004654fc` | same as above but silent (flags=0). Used by battery/audio telemetry. |
| `send_input_event_to_peers` | 0x464ef0 | — | `(msg_id,event_a,event_b,ctx)` | **3 / 7** | 12B fixed: `[2..3]id [4..7]a [8..11]b` | `DAT_004654fc` | type‑3 listener is **slave‑only**; guarded by `lens_side()=='\x01'` ⇒ **R→L input/touch forwarding**. RX=`SlaveInputEventReplyListener`→`FUN_00443cb8(id,a,b)`. |
| `SendIdleCommandtoScheduleManager` | 0x4652b8 | tFx | `(a1,a2,a3,ctx)` | 5 / 0xe | 8B, all‑zero body | `DAT_004654fc` | **master‑only** (`lens_side!=1`→‑1); local schedule‑mgr IPC via `xQueueSend(*DAT_00465770,…,2000)`. app‑idle lifecycle. Panics (`FUN_005f99ec`+`while(1)`) if uninit. |
| `SendStartUpCommandtoScheduleManager` | 0x465524 | tFx | `(app_id,a2,a3,ctx)` | 5 / 0xf | 8B, appID in body | `DAT_00465790` | master‑only; app‑startup lifecycle to schedule mgr. |
| `sync_alloc_retry` | 0x463e98 | — | `void*(uint size)` | — | — | — | `fw_malloc` with up to **10 retries**, exponential backoff `os_delay_ms(1,2,4,…,512)`. Every poster allocs its 0xc descriptor and `len+8` body through this. |

### 5. TinyFrame type ↔ listener map (who receives what)

From `SyncModuleInit` @ 0x45ec54 (role from `_private_getCurrentRoleStatus` @ 0x45a8fc: 1=master/R, 2=slave/L):

- **Master `TF_Init(1)`** registers type listeners **0, 1, 4**.
- **Slave `TF_Init(0)`** registers type listeners **2, 3, 1, …** (last `TF_AddTypeListener` truncated — likely also 0).

Cross‑referencing the RX handlers in the bundle:

| TF type | registered on | RX handler | opcode checked | TX primitive that emits it |
|---------|---------------|-----------|----------------|----------------------------|
| **1** | **both** | `UserDataReplyListener` @0x45b90c | `==9` | `send_app_command_to_peer`, `SendDataToBothExt` |
| **2** | slave (L) | app‑cmd listener (`_AsyncReflash…`/`_AsyncStartUP…` path) | 1/3/5/0x10 | `post_app_command` family (R→L) |
| **3** | slave (L) | `SlaveInputEventReplyListener` @0x45bbd4 | `==7` | `send_input_event_to_peers` (R→L) |
| **4** | master (R) | `sched_recv_peer_sync_data` @0x45ba68 | `==0xc` | `send_data_to_peer[_noevent]` (L→R) |
| **5** | — (local) | schedule‑manager queue `DAT_00465770` | 0xe/0xf | `SendIdle/StartUpCommandtoScheduleManager` (master‑local) |

**This nails the directionality**: type‑2/3 sinks live on the slave ⇒ R‑drives‑L; type‑4 sink lives on the master ⇒ L‑reports‑R; type‑1 is symmetric.

### 6. Mapping to your GOAL

**(a) Push per‑lens content R→L.** Two channels:
- **`send_peer_app_cmd_op3(appID, data, len, ctx)`** (type2/op3) or `request_display_startup` (type2/op1) — these hit the slave's **app command** listener, i.e. they drive the peer *app* (display/reflash). Best when L is running your hot‑loaded app and you want it to render given content.
- **`send_app_command_to_peer` / `SendDataToBothExt`** (type1/op9) — generic user‑data to the peer app's data handler (`find_ui_DataHandler_by_id`). Use for raw per‑lens buffers; `SendDataToBothExt`'s `sub_id` gives you a tag. Payload cap 10240 B/frame.

**(b) Synchronized present ("both eyes flip together").** The observed mechanism is **not** a single atomic opcode; it's master‑orchestrated:
- `_AsyncReflashApplicationDataHandlerCb` @0x45ad6a → **`send_peer_app_cmd_op3` (type2/op3)** is the "reflash/present the app on the peer" trigger. `AsyncRequestDisplayReflash` @0x45ae4e queues it (prepends a 4‑byte `token`).
- Coupled with **`DispStartBlockingEn` @0x45c024** (master‑only; `lens_side==2`→`0xfffffffe`) which takes `mutex *DAT_0045c374`, sets flag `*DAT_0045c378`, and arms a timer (≤15000 ms) — a barrier so the master waits for the slave's present before flipping. `DispStartBlockingCancel`/`DispStartBlocking_TimerCb` release it. And `FUN_004657be` @0x4657be compares three cross‑struct fields and calls `FUN_00447eee` on mismatch — a present‑consistency check.
- So the native "flip together" recipe ≈ **master sends op3 reflash to L, both present, master uses DispStartBlocking barrier to phase them.** (This matches your existing `barrier-L` finding — you re‑implemented this phasing yourself.) I could not see the exact two‑phase commit inside the truncated `post_app_command` tail, so treat the *precise* barrier handshake opcode as inferred, not proven.

**(c) Relay L→R (screenshot).** Use **`send_data_to_peer(app_id, data, len, ctx, event_type)`** (type4/op0xc) from the slave — its sink `sched_recv_peer_sync_data` is master‑only, so it is the canonical L→R path; `dashboard_ext_report_pb_state_to_peer` @0x525fbe calls it exactly this way under `lens_side()==2`. Use `event_type=5` to fire a data event on R, or `send_data_to_peer_noevent` for silent. **Chunk screenshots to ≤10240 B** per frame (the `len < 0x2801` cap) and carry a sub‑command in payload `[8]` + sequence in the appID/eventType fields.

### 7. Observed `appID` (service) + payload‑`[8]` sub‑command space

| appID | service (module) | sub‑cmd `[8]` seen | via |
|-------|------------------|--------------------|-----|
| `0x10` | onboarding.data_mgr | `0xd` flag‑send, `0xe` flag‑reply, `9` process‑sync | `send_data_to_peer(…,5)` |
| `0x1f` | dashboard.ext | `3` pb‑state (+bool) | `send_data_to_peer(…,5)` |
| `0x105` | charger_common / ring‑batt | `8` battery‑info(reason), `6` ring‑batt‑req, `4` req‑notify | `send_data_to_peer_noevent` |
| `0x10c` | service.audio.manager | syncMsg `1..4` | `send_data_to_peer_noevent` |

### 8. Practical cautions / uncertainty

- **Two independent init gates**: app‑command family checks `*DAT_00464968`; peer‑data family checks `*DAT_004654fc` (startup checks `*DAT_00465790`). Both must be non‑null or you get `‑1` (and the ScheduleManager variants **hard‑panic into `while(1)`**, not a soft error).
- `msgType` (byte 0) **is** the TinyFrame type and is **only written into the descriptor under `lens_side()==1`** in `post_app_command`/`send_input_event_to_peers`; the slave‑side branch is truncated in the dump. For a hot‑loaded app on *both* lenses, verify which side actually flushes the queue before relying on symmetric behavior.
- Several function tails (`post_app_command`, `send_app_command_to_peer`, `SendDataToBothExt`, `send_data_to_peer[_noevent]`, `send_input_event_to_peers`) are **cut off after the packet‑build stage** in this bundle — the header/opcode facts above are solid (direct byte stores), but the final enqueue/`TF_Send`/reply‑listener wiring for each is inferred from `SyncModuleSendDataHandler` + the RX listeners, not read end‑to‑end per function.
- `send_input_event_to_peers` deviates from the generic layout: it is a **fixed 12‑byte frame** (`[2..3]=id, [4..7]=event_a, [8..11]=event_b`), so bytes 6‑7 are *event data*, not a length — don't reuse it as a data pipe.

**Source file:** `/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/peer_bundle.txt`

---

## Receive, dispatch & wire format

Now I have the full picture. Here is my analysis.

---

### RECEIVE / DISPATCH / WIRE FORMAT — Even G2 fw 2.2.4.34 inter-lens peer subsystem

Scope: how a peer UART frame becomes a call into a custom app's `dataCb`, the exact byte layout, how the target app+callback is chosen, and how ACKs flow back. All addresses/offsets are read directly from `peer_bundle.txt`.

---

### 1. The transport is TinyFrame over UART

`SyncModuleInit @ 0x45ec54` builds the whole stack. It calls `TF_Init(...)` (stored in `*DAT_0045ef60` = the TF instance) and registers **per-type receive listeners** with `TF_AddTypeListener(tf, type, cb)`:

| role (`_private_getCurrentRoleStatus` result) | `TF_AddTypeListener` calls (type → cb global) |
|---|---|
| **master / side 1** (status==1) | type `0`→`DAT_0045efb8`, type `1`→`DAT_0045efbc`, type `4`→`DAT_0045efc0` |
| **slave / side 2** (status==2) | type `2`→`DAT_0045efe0`, type `3`→`DAT_0045efe4`, type `1`→`DAT_0045efbc`, … *(list truncated in bundle at line ~1339)* |

So the TinyFrame **type field is the primary demux key**, and — as shown below — it always equals `payload[0]` (the field the send helpers call `msgType`). `payload[1]` (`opcode`) is a secondary discriminator each listener re-checks.

RX data flow (thread hops):

```
UART RX  → uart_thread_handler @0x4e1d68 (thread "sync.module.uart")
            ├ opens UART dev via FUN_00555e7a(0x6000,1,…)  (0x6000 = 24KB rx buf)
            ├ SyncModuleInit()  (installs TF listeners)
            └ loop @LAB_004e1f2c: FUN_004486ec(sem,7,2,-1) → drain UART bytes
                → SyncModuleReceivedDataHandler @0x45d860
                     └ FUN_004a7bba(*DAT_0045e0e8, data, len)   ← = TF_Accept(tf, buf, len)
                          └ (complete frame) → TF type-listener fires  [UART/TF thread ctx]
                               ├ TF_Respond ack  (FUN_004a827a)
                               └ SendUserDataToThreadPool(appID, payload, len, sub)  @0x45aab0
                                    └ submit_work(pool DAT_0045b4b4, id, copy, len, sub)
                                         → _userDataHandlerCb @0x45aa54            [thread-pool ctx]
                                              └ find_ui_DataHandler_by_id(appID, data, len, sub)
                                                   └ **the custom app's registered dataCb**
```

Key point: the app callback runs in a **thread-pool worker**, decoupled from the UART thread, on a **private `fw_malloc` copy** of the payload that `_userDataHandlerCb` frees the instant the callback returns.

---

### 2. Wire packet layout (the TinyFrame *payload*)

TinyFrame adds its own framing (SOF / frame_id / type / len / checksum). Inside that, every app/peer message uses this 8-byte header + body (read off the send builders `post_app_command @0x463f1a`, `send_app_command_to_peer @0x4644c4`, `send_data_to_peer @0x464c28`, and confirmed by the receive decoders):

**Standard "AppMsg" header (types 1/2/4):**

| off | size | field | notes |
|----|----|----|----|
| 0 | u8 | `msgType` | **equals the TinyFrame type** (1/2/4…) |
| 1 | u8 | `opcode` | sub-command; each listener asserts a fixed value |
| 2 | u16 LE | `appID` | routing key → `find_ui_DataHandler_by_id` |
| 4 | u16 LE | `sub`/`eventType`/`flags` | app-visible; 0 for the "noevent" senders |
| 6 | u16 LE | `len` | body length (≤ 0x2800 = 10240, enforced in `post_app_command`) |
| 8 | `len` | `payload[]` | delivered to the app dataCb |

**Input-event variant (type 3) — different, shorter, no len field** (`send_input_event_to_peers @0x464ef0`, total 0xC bytes):

| off | size | field |
|----|----|----|
| 0 | u8 | `msgType` = 3 |
| 1 | u8 | `opcode` = 7 |
| 2 | u16 LE | `msg_id` (event type) |
| 4 | u32 LE | `event_a` (code) |
| 8 | u32 LE | `event_b` (value) |

Complete observed type/opcode matrix:

| TF type = `msgType` | `opcode` | sender fn (addr) | receiver listener | meaning |
|---|---|---|---|---|
| 2 | 1 | `request_display_startup` 0x4642d6 → `post_app_command` | type-2 listener (slave) | display **startup** |
| 2 | 3 | `send_peer_app_cmd_op3` 0x46435a | type-2 listener (slave) | display **reflash/present** |
| 2 | 5 | `evenhub_open` 0x4643de | type-2 listener | app open |
| 2 | 0x10 | `send_peer_app_ctrl_op16` 0x464462 | type-2 listener | app ctrl/close |
| **1** | **9** | `send_app_command_to_peer` 0x4644c4 | **UserDataReplyListener 0x45b90c** | app user-data (**bidirectional**) |
| **4** | **0xc** | `send_data_to_peer` 0x464c28 / `_noevent` 0x464988 | **sched_recv_peer_sync_data 0x45ba68** | user-data w/ eventType |
| **3** | **7** | `send_input_event_to_peers` 0x464ef0 | **SlaveInputEventReplyListener 0x45bbd4** | mirror R→L input |
| 5 | 0xe | `SendIdleCommandtoScheduleManager` 0x4652b8 | schedule-mgr queue | idle cmd (master-only) |
| 5 | 0xf | `SendStartUpCommandtoScheduleManager` 0x465524 | schedule-mgr queue | startup cmd (master-only) |

---

### 3. The three receive decoders (exact offset math)

All three take `(void *transport /*=TF instance*/, peer_pkt_hdr_t *msg /*=TF_Msg*/)`, read the payload pointer as `puVar = *(ushort**)(msg+1)` and the received length as `msg[1].event_type`.

**`UserDataReplyListener @0x45b90c`** (TF type 1) — despite the name, this is a *receiver*:
```
if (*puVar2 >> 8 == 9) {                 // assert opcode(byte1)==9
    id = puVar2[1];                      // appID  @off2
    FUN_0043c0e4(&stack,0x18,0);         // zero a 0x18 TF_Msg
    for(i=0;i<msg[1].event_type;i++){}   // (empty — decompiler-lost copy/checksum loop)
    FUN_004a827a(transport,&stack);      // = TF_Respond → ACK
    SendUserDataToThreadPool(id, puVar2+4, puVar2[3], puVar2[2]);
    //                            ^payload@off8  ^len@off6  ^sub@off4
}
```

**`sched_recv_peer_sync_data @0x45ba68`** (TF type 4) — identical shape, only the opcode check differs: `*puVar2 >> 8 == 0xc`, then the same `SendUserDataToThreadPool(id, puVar2+4, puVar2[3], puVar2[2])` and the same `FUN_004a827a` ACK.

**`SlaveInputEventReplyListener @0x45bbd4`** (TF type 3): asserts `*puVar5 >> 8 == 7`, then
```
uVar1 = puVar5[1];               // msg_id / event type  @off2
uVar3 = *(u32*)(puVar5+2);       // event_a  @off4
uVar4 = *(u32*)(puVar5+4);       // event_b  @off8
FUN_004a827a(transport,&stack);  // ACK
FUN_00443cb8(uVar1,uVar3,uVar4); // inject the input event into the LOCAL (slave) input pipeline
```
This is the R→L input mirror: master forwards its button/touch/gesture events and the slave re-injects them so both lenses react in lock-step. Note it does **not** go through the thread pool — it's dispatched inline.

`*puVar >> 8` extracts `byte[1]` because `*puVar` is the LE u16 = `byte0 | byte1<<8`; so every decoder is checking the **opcode**, having already been selected by TF type = byte0.

---

### 4. What the app dataCb actually receives

`SendUserDataToThreadPool @0x45aab0`:
```
arg2 = fw_malloc(len);              // fresh buffer
fw_memcpy(arg2, data, len);         // copy payload OUT of the soon-to-be-freed TF frame
submit_work(DAT_0045b4b4, id, arg2, len, sub);   // hand off to thread pool
```
The pool worker is `_userDataHandlerCb @0x45aa54(ushort id, void*data, uint len, uint flags)`:
```
find_ui_DataHandler_by_id(id, data, len, (ushort)flags);   // registry lookup by appID
fw_free(data);                                             // frees the copy after cb returns
```

So a **custom app registers a handler keyed by its `appID`** (via the UI/display "DataHandler" registry that `find_ui_DataHandler_by_id` walks — that registry itself isn't in this bundle). At delivery the app receives exactly:
- **`appID`** (already used for routing),
- **`data`** = pointer to the `len`-byte body (wire offset 8+), a private copy,
- **`len`** = body length,
- **`flags`** = the 16-bit `sub`/`eventType` field (wire offset 4-5).

The app never sees `msgType`/`opcode`/the length header — the framework consumes those. The `sub`/`eventType` u16 is the one app-controllable "sub-channel" byte-pair you get for free (e.g. `RPC_Onboarding*` senders pass `5`; `send_app_command_to_peer` and the `_noevent` senders hardwire `0`). Because delivery is on a worker thread over a copy that is freed on return, **the dataCb must consume synchronously** (copy anything it wants to keep).

---

### 5. ACK / reply handshake

Every standard receive (`UserDataReplyListener`, `sched_recv_peer_sync_data`, `SlaveInputEventReplyListener`) immediately calls `FUN_004a827a(transport, &zeroed_0x18_TF_Msg)` = **`TF_Respond`**, i.e. an empty frame echoing the incoming `frame_id`. That closes the loop on the sender side: the TX pump `SyncModuleSendDataHandler @0x45e9e8` transmits via `FUN_004a8286(tf, msg, cb, ctx, 0x32)` = **`TF_Query`** (send + one-shot reply-listener, timeout `0x32`=50 ms). The `(cb,ctx)` reply-listener pair is chosen by frame type from the `DAT_0045ef58/5c … ef84/88` table — these are the *sender-side* ack handlers, distinct from the type-listeners above. If the ACK doesn't arrive in 50 ms the query listener times out. This is a reliable, per-frame request/ack channel — not fire-and-forget.

(`SyncTimeoutDetectionThreadStartup @0x45d6d0` + `DispStartBlocking*` add a separate liveness/"hold display until peer ready" layer; `DispStartBlockingEn @0x45c024` is master-only — returns `0xfffffffe` if `lens_side()==2` — and is the barrier used for the "both eyes flip together" present, released by `DispStartBlockingCancel @0x45c1f0`.)

---

### 6. Implications for the custom dual-lens app

- **(a) push per-lens content R→L / (c) relay L→R:** use **type 1 opcode 9** via `send_app_command_to_peer(appID,data,len,ctx)` — it's registered on *both* sides (`type 1 → DAT_0045efbc`), so it's genuinely bidirectional, and it lands in your app's dataCb by `appID`. Alternatively **type 4 opcode 0xc** (`send_data_to_peer(appID,data,len,ctx,eventType)`) gives you the extra 16-bit `eventType` sub-selector, but master-registration of type 4 is confirmed while slave-side type-4 registration is in the truncated region (see uncertainties). Both funnel through the same `SendUserDataToThreadPool → _userDataHandlerCb → find_ui_DataHandler_by_id` path, so a single registered handler receives either. Body cap is **10240 bytes** (`len < 0x2801` in `post_app_command`); a screenshot must be **chunked** (carry your own seq/offset in the payload or in the `eventType` u16).
- **(b) synchronized present:** the R→L input-mirror (type 3/opcode 7, `send_input_event_to_peers` → `SlaveInputEventReplyListener` → `FUN_00443cb8`) plus the type-2 startup/reflash opcodes (1/3, master→slave) and the master-only `DispStartBlocking` barrier are the native "flip together" primitives. Your custom app can piggyback on type-1/4 app-data to signal "ready", but the actual atomic flip is gated by that display-blocking barrier which only the master arms.

---

### 7. Uncertainties (honest)

- **Type-2 and type-0 listeners** (`DAT_0045efe0`, `DAT_0045efb8`) are not resolved by name in this bundle; I inferred their purpose from the opcodes their matching senders emit (display startup/reflash/open/ctrl). The `_Async*DataHandlerCb` functions (0x45ab8e/0x45ad6a/0x45af48) are **sender-side** thread-pool workers that *call* `request_display_startup`/`send_peer_app_cmd_op3`/`send_input_event_to_peers`, not receive handlers — don't confuse them with the TF listeners.
- **Slave type-4 registration**: the slave `TF_AddTypeListener` list is cut off at line ~1339 (`…,1,DAT_0045efbc); TF_AddTypeListener(*`), so I can confirm master receives type-4 user-data but cannot confirm/deny the slave also registers type 4. If your L-lens must receive `send_data_to_peer`, verify this in the full `SyncModuleInit`.
- **TF helper identities** (`FUN_004a7bba`=TF_Accept, `FUN_004a827a`=TF_Respond, `FUN_004a8286`=TF_Query) are inferred from the `TF_Init`/`TF_AddTypeListener` named imports and the observed accept/respond/query behavior — consistent but not symbol-confirmed.
- `SyncModuleReceivedDataHandler` feeds `*DAT_0045e0e8` while `SyncModuleInit` stores the TF instance in `*DAT_0045ef60`; these are almost certainly the same instance in two global slots, but I did not see an assignment linking them.
- **`find_ui_DataHandler_by_id`** (the appID→dataCb registry) and the registration API a custom app would call are outside this bundle — that's the one piece you'd need to locate to actually hook a callback.
- The empty `for` loop in the two `*ReplyListener`s iterating `msg[1].event_type` is a decompiler artifact (an inlined copy/checksum whose body was lost); it has no functional effect on dispatch.

Relevant source: `/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/peer_bundle.txt`.

---

## Cross-lens display coordination (the "both eyes flip" sync)

Based on a full read of the bundle, here is my analysis of the cross-lens display-coordination subsystem.

---

## Cross-lens display coordination ("both eyes flip together") — G2 fw 2.2.4.34

### 1. Role / side model (who is master)

Two independent side identifiers drive everything:

- `lens_side()` → returns **1 = master (R / side1)**, **2 = slave (L / side2)**. This is the physical-side gate used all over the bundle (e.g. `post_app_command` @0x463f1a line 1447, `send_input_event_to_peers` @0x464ef0 line 1929, `DispStartBlockingEn` @0x45c024 line 881).
- `_private_getCurrentRoleStatus` @**0x45a8fc** reads NVM/config key **0x9c** five times (`FUN_0047e802(0x9c,0,&v)`), requires all five to agree, then **maps stored value 1 → returns 2, else → returns 1** (stores into `*DAT_0045b478`); inconsistent reads → returns **3** (error). `SyncModuleInit` @0x45ec54 branches on the low byte: **==1 ⇒ master path `TF_Init(1)`**, **==2 ⇒ slave path `TF_Init(0)`**.

The TinyFrame ("TF") transport is the link layer over `sync.module.uart`. `SyncModuleInit` registers **type listeners**, and the "type" is the first payload byte (see §3):

| Role | `TF_Init` arg | Registered TF types (byte0) |
|---|---|---|
| Master (1) | `TF_Init(1)` | **0, 1, 4** |
| Slave (2) | `TF_Init(0)` | **2, 3, 1, …** (list truncated at line 1339) |

So **display/input commands (types 2 & 3) are listened for by the SLAVE** = master→slave direction; **telemetry (type 4) is listened for by the MASTER** = slave→master; **type 1 (user data) is registered on both** = bidirectional.

---

### 2. The three master→slave display primitives share one pipeline

`AsyncRequestDisplayStartUp`, `AsyncRequestDisplayReflash`, and `AsyncSendInputEventToPeers` are **identical in shape**: they prepend a 4-byte word, `submit_work()` to a thread pool, and the pool's worker sleeps then calls a low-level peer-send.

**AsyncRequestDisplayReflash @0x45ae4e** (StartUp @0x45ac72 is byte-identical except the worker & log strings):
```
arg2 = fw_malloc(len + 4);
arg2[0..3] = token   (LE 32-bit)          // 4th param "token"
memcpy(arg2+4, data, len);
submit_work(DAT_0045ba60, id, arg2, len+4, 0);   // DAT_0045ba60 = _AsyncReflashApplicationDataHandlerCb
```

**_AsyncReflashApplicationDataHandlerCb @0x45ad6a** (the pool worker):
```
uVar1 = *data;              // = token  (the 4 bytes we prepended)
FUN_00453a80(uVar1);        // *** sleep(token) ms ***  <-- token is a DELAY, not a correlation id
if (len == 4)  send_peer_app_cmd_op3(id, 0,       0,      0);   // no payload
else           send_peer_app_cmd_op3(id, data+1,  len-4,  0);   // data+1 (uint*) skips the 4-byte token
fw_free(data);
```

Two hard facts here:

1. **The 4th argument named `token` is consumed as a millisecond delay**, not an ID. `FUN_00453a80` is the same delay routine called as `FUN_00453a80(100)` behind a `withDelay` flag in `dashboard_ext_report_pb_state_to_peer` @0x525fbe (line 2797). So `token` = "wait N ms on the master's worker thread, *then* transmit the reflash to the slave." It is the cross-lens **alignment knob**.
2. **The reflash worker does NO local present.** It only forwards to the peer (`send_peer_app_cmd_op3`). `AsyncRequestDisplayReflash` is *only the "tell the other eye to repaint" half* — see §7.

Worker/threadpool map (all confirmed by the `submit_work(DAT_…)` targets):

| Async API | addr | threadpool worker (DAT) | worker addr | forwards via |
|---|---|---|---|---|
| `AsyncRequestDisplayStartUp` | 0x45ac72 | `DAT_0045b4cc` | `_AsyncStartUPApplicationDataHandlerCb` 0x45ab8e | `request_display_startup` |
| `AsyncRequestDisplayReflash` | 0x45ae4e | `DAT_0045ba60` | `_AsyncReflashApplicationDataHandlerCb` 0x45ad6a | `send_peer_app_cmd_op3` |
| `AsyncSendInputEventToPeers` | 0x45b050 | `DAT_0045bbcc` | `_AsyncSendInputEventToPeersDataHandlerCb` 0x45af48 | `send_input_event_to_peers` |

(`AsyncSendInputEventToPeers` uses a fixed 0xE-byte record: `[0..3]=token, [4..5]=eventType, [6..9]=eventCode, [10..13]=eventValue`; worker reads them at offsets +0/+4/+6/+10 and calls `send_input_event_to_peers(eventType, code, value, 0)`.)

---

### 3. Wire format (what actually goes over the UART)

All three forward into `post_app_command` @**0x463f1a**, which builds an **8-byte header + payload** (offsets are exact from lines 1436-1445):

```
[0]     msgType   (= TF type / routing class)
[1]     opcode
[2..3]  appID     (LE)      <- your "id"
[4..5]  eventType (LE)
[6..7]  len       (LE)
[8..]   payload (len bytes; capped: post_app_command rejects len >= 0x2801 = 10241)
```
It then sets a control block `local_24`: `[0]=ctx`, ushort@+4 = msgType (TF routing), ushort@+6 = len+8, `[2]=payload ptr`; **and only enqueues to the TX queue when `lens_side()==1` (master)** (line 1447). `SyncModuleSendDataHandler` @0x45e9e8 drains that queue and TF-sends.

Opcode / type map I recovered from the builders:

| Sender fn | byte0 (type) | byte1 (opcode) | meaning |
|---|---|---|---|
| `request_display_startup` 0x4642d6 | **2** | **1** | open/startup app on peer |
| `send_peer_app_cmd_op3` 0x46435a | **2** | **3** | **reflash (repaint) app on peer** |
| `evenhub_open` 0x4643de | 2 | 5 | evenhub open |
| `send_peer_app_ctrl_op16` 0x464462 | 2 | 0x10 | app ctrl |
| `send_input_event_to_peers` 0x464ef0 | **3** | **7** | inject input event on peer |
| `send_app_command_to_peer` 0x4644c4 / `SendDataToBothExt` 0x46471e | 1 | 9 | user data (bidir) |
| `send_data_to_peer(_noevent)` 0x464c28/0x464988 | 4 | 0xc | generic sync data (slave→master) |
| `SendIdleCommandtoScheduleManager` 0x4652b8 | 5 | 0xe | schedule-mgr idle |
| `SendStartUpCommandtoScheduleManager` 0x465524 | 5 | 0xf | schedule-mgr startup |

Note types **2 and 3 are exactly the slave-registered listener types** → confirms reflash/startup/input are master→slave.

---

### 4. Receive side (what the slave does with a reflash) — and the gap

The three receive listeners in the bundle dispatch on **byte1 (opcode)** = high byte of the first payload ushort:

| Listener | addr | matches opcode | action |
|---|---|---|---|
| `UserDataReplyListener` | 0x45b90c | `>>8 == 9` | `SendUserDataToThreadPool(id, payload+8, len@+6, evt@+4)` → `_userDataHandlerCb` → **`find_ui_DataHandler_by_id(id,…)`** |
| `sched_recv_peer_sync_data` | 0x45ba68 | `>>8 == 0xc` | same `SendUserDataToThreadPool(...)` dispatch |
| `SlaveInputEventReplyListener` | 0x45bbd4 | `>>8 == 7` | reads keycode@+2, a@+4, b@+8 → `FUN_00443cb8(keycode,a,b)` (inject input locally) |

The receive-side offsets `payload+8 / len@+6 / evt@+4 / id@+2` mirror `post_app_command`'s header exactly — the loop is self-consistent.

**The critical gap:** the **type-2 receive handler that actually executes opcode 3 (reflash) / opcode 1 (startup) on the slave is NOT in this 54-function bundle.** The slave registered `DAT_0045efe0` for type 2 (SyncModuleInit line 1336) but that function isn't included. So I can see the master emit "reflash appID X", but I **cannot prove from this bundle how the slave routes opcode-3 to a specific app's repaint**, nor whether it will honor an arbitrary hot-loaded appID vs. only known compositor apps. That link is the single biggest unknown for your goal (§7).

---

### 5. `DispStartBlocking*` — the real "hold both eyes" barrier

This is the primitive that gates the *master's own* present so it can wait for the slave. It is **master-only** and uses one boolean gate + a watchdog timer:

- `*DAT_0045c378` — the **display-start-block flag** (0 = free, 1 = blocked)
- `*DAT_0045c374` — mutex protecting it
- `*DAT_0045c39c` — one-shot timer handle

**`DispStartBlockingEn(timeoutMs)` @0x45c024:**
```
if (lens_side()==2) return 0xfffffffe;      // slave cannot block -> master-only
if (timeoutMs > 15000) timeoutMs = 15000;   // hard cap 15 s
lock;
if (*DAT_0045c378 == 0) {                    // not already blocked
    *DAT_0045c378 = 1;                       // *** raise the gate ***
    FUN_004484ea(*DAT_0045c39c, timeoutMs);  // arm watchdog timer
} else return 0xffffffff;                     // already blocked -> reject
unlock;
```
**`DispStartBlocking_TimerCb` @0x45bf8a** (watchdog fires): `*DAT_0045c378 = 0` — auto-release on timeout (safety so a missing slave can't wedge the master forever).

**`DispStartBlockingCancel` @0x45c1f0** (master-only): stops the timer (`FUN_00448574`/`FUN_0044852a` on `*DAT_0045c39c`) and clears `*DAT_0045c378 = 0` — the **explicit release** that lets the master flip.

So `*DAT_0045c378` is a gate that the *local display-startup path consults* (that consumer is not in this bundle, but the flag has no other purpose): while set, the master defers its own present; clearing it (by cancel, or by the 15 s watchdog) lets it flip.

---

### 6. Reconstructed synchronized-present protocol

Combining §2/§5 (parts marked **[inferred]** are not fully provable from this 54-function slice):

1. Master decides to present new content to both eyes.
2. Master calls **`DispStartBlockingEn(T)`** → raises `*DAT_0045c378`, holding its **own** flip, with watchdog `T` (≤15 s). **[inferred: local present path honors this flag]**
3. Master calls **`AsyncRequestDisplayReflash(appID, data, len, token)`** (or `…StartUp` to open the app first). Worker sleeps `token` ms, then transmits opcode-3/type-2 to the slave.
4. Slave's type-2 handler renders and presents; slave acks back — the ack channel exists (`SlaveInputEventReplyListener`/`UserDataReplyListener` both send a reply frame via `FUN_004a827a(transport,…)` before dispatching). **[inferred: an ack drives step 5]**
5. Master calls **`DispStartBlockingCancel`** → clears the gate → master flips. Both eyes now flip within one alignment window; the `token` delay + the block are the two knobs that squeeze the delta toward 0 (the "two-phase present" behavior).

The watchdog cap (15 s) and the auto-clear on timer confirm the design intent: *master waits for the slave, but never indefinitely.*

---

### 7. CRUCIAL — can a custom master-side app drive BOTH lenses via `AsyncRequestDisplayReflash`/`StartUp`?

**What the call gives you (proven):**
- `id` = **your appID (ushort)**. It is copied verbatim into header `[2..3]` and is the routing key on the slave (`find_ui_DataHandler_by_id(id,…)` for the user-data path; the reflash path keys on the same appID field).
- `data`/`len` = an **opaque payload delivered to the slave app registered under `id`** (capped <10241 B by `post_app_command`; for reflash the app-payload is whatever you pass minus the token word).
- `token` = **millisecond delay before the master transmits** (via `FUN_00453a80`). Use `0` for "send now", or a small value to bias the slave later to match a deferred master flip.

**Hard caveats (this is the honest part):**

1. **`AsyncRequestDisplayReflash` does NOT repaint the master.** `_AsyncReflashApplicationDataHandlerCb` (0x45ad6a) only forwards to the peer. To flip *your* eye you must **separately repaint the master locally** and use Reflash to flip the *slave*. Reflash is the "other eye" half only. `token` + `DispStartBlockingEn/Cancel` are how you line them up.

2. **It carries a trigger + payload, not a framebuffer.** For "both lenses show ITS content," the custom app must already be resident on **both** lenses (you have this — hot-loaded on both), and per-lens pixels must arrive by a **separate content channel first**: from the master use `send_data_to_peer(appID, buf, len, ctx, evt)` (type 4/op 0xc) or `send_app_command_to_peer`/`SendDataToBothExt` (type 1/op 9) — both land in the slave via `find_ui_DataHandler_by_id(appID,…)`. Then `AsyncRequestDisplayReflash(appID, …)` is the "now flip" trigger.

3. **The decisive unknown: the slave's opcode-3 executor is not in this bundle.** Whether the slave's type-2 handler dispatches reflash to an *arbitrary custom appID's* present callback, or only to compositor-known IDs, is not observable here. If it validates appID against a built-in registry, `AsyncRequestDisplayReflash(customID)` will be dropped on the slave. **This must be tested on-device** (send Reflash for your custom ID and watch the slave TF log line `0xee`/`0xc8...` in `_AsyncReflashApplicationDataHandlerCb`'s counterpart, or instrument `find_ui_DataHandler_by_id`).

4. **`DispStartBlockingEn` is genuinely master-only** (`lens_side()==2 → 0xfffffffe`), so the barrier design assumes the master orchestrates. That matches your R=master topology.

**Practical recipe for your custom app (master-driven lockstep):**
```
// once: custom app resident on both lenses, registers a UI data handler for CUSTOM_ID on the slave
send_data_to_peer(CUSTOM_ID, leftEyeBuf, n, 0, evt);   // push L-eye content R->L (type4/op0xc)
DispStartBlockingEn(200);                               // hold master flip, 200 ms watchdog
// ... paint master's own R-eye locally ...
AsyncRequestDisplayReflash(CUSTOM_ID, reflashArgs, m, token);  // token≈measured UART+render latency
// on slave-ack (or a short fixed wait):
DispStartBlockingCancel();                              // release -> both flip
```
`token` and the `DispStartBlockingEn` timeout are the two dials; start with `token=0` and tune from the observed L/R delta.

---

### 8. Summary of certainties vs. gaps

**Proven from code:** master=side1/role-derived; the Async→threadpool→`post_app_command` pipeline and its 8-byte header offsets; `token` = ms delay (not an ID); reflash=type2/op3, startup=type2/op1, input=type3/op7, sync-data=type4/op0xc, user-data=type1/op9; only the master enqueues these (`lens_side()==1`); receive dispatch keys on appID via `find_ui_DataHandler_by_id`; `DispStartBlocking*` is a master-only present gate with 15 s watchdog.

**Not in this bundle / must verify on device:** the slave-side type-2 handler that *executes* reflash/startup (does it accept custom appIDs?); the exact consumer of `*DAT_0045c378` in the local present path; the precise ack that should trigger `DispStartBlockingCancel`; and whether `token`+block actually drives delta→0 for your content (empirical).

Source: `/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/peer_bundle.txt`.

---

## Existing app practices & usable primitives for us

I have read the full 54-function bundle. Here is the analysis.

---

# G2 fw 2.2.4.34 — Inter-Lens Peer Comms: Existing Practices & Primitives Usable by a Custom App

## 1. Everything funnels through one send path

Every peer send in this cluster builds the **same 12-byte descriptor** and enqueues it; `SyncModuleSendDataHandler` (`0x45e9e8`) dequeues it and hands it to the TinyFrame transport (`FUN_004a8286`, the `TF_Send` on the `sync.module.uart` link). The canonical builder is:

**`post_app_command @ 0x463f1a`** — `int post_app_command(ushort appID, void *data, ushort len, void *ctx, byte opcode, byte msgType, ushort eventType)`

- Rejects `len >= 0x2801` → **hard payload cap of 0x2800 = 10240 bytes** on this path.
- Allocates a 0xC descriptor + a `len+8` payload buffer, fills an **8-byte app header** + body, sets the descriptor's `type` field = `msgType`, and (for the master-originated opcodes) gates the enqueue on `lens_side()=='\x01'`.

Descriptor layout (0xC bytes), as written here and read back in `SyncModuleSendDataHandler`:

| off | field | set at | read at |
|---|---|---|---|
| +0 | `ctx` (reply/callback correlation ptr) | `*local_24 = ctx` | `local_c = *local_24` |
| +4 | `type` (== msgType; selects TF wire channel) | `*(ushort*)(local_24+1)=msgType` | `local_1c` / `uVar1` |
| +6 | `totalLen` (= len+8) | `*(ushort*)((int)local_24+6)` | `local_14` |
| +8 | payload ptr | `local_24[2]` | `local_10` |

## 2. The 8-byte app-layer header (identical across all wrappers)

Built byte-for-byte in `post_app_command`, `send_app_command_to_peer`, `SendDataToBothExt`, `send_data_to_peer*`, `send_input_event_to_peers`; decoded in the receive listeners as `puVar2` (`ushort*`):

| off | field | encoder | decoder |
|---|---|---|---|
| 0 | **msgType** (byte) | `*(byte*)p = msgType` | `*puVar2 & 0xff` |
| 1 | **opcode** (byte) | `*(byte*)(p+1) = opcode` | `*puVar2 >> 8` ← **dispatch key** |
| 2–3 | **appID** (LE u16) | `p[2],p[3]` | `puVar2[1]` |
| 4–5 | **eventType/subID** (LE u16) | `p[4],p[5]` | `puVar2[2]` |
| 6–7 | **payloadLen** (LE u16) | `p[6],p[7]` | `puVar2[3]` |
| 8.. | **payload** | `memcpy(p+8,data,len)` | `puVar2 + 4` |

So the first wire u16 is `(msgType | opcode<<8)`, and **all receive listeners dispatch on `>>8` (opcode)** then route by appID.

## 3. The msgType(=TF type) → direction → listener map

`SyncModuleInit @ 0x45ec54` calls `TF_Init(1)` for **master (role 1 = R/side1)** and `TF_Init(0)` for **slave (role 2 = L/side2)** (role from `_private_getCurrentRoleStatus @ 0x45a8fc`), then registers listeners **asymmetrically** by type:

- Master registers types **0, 1, 4**
- Slave registers types **2, 3, 1** (+1 more, truncated in dump)

Cross-referencing with the sender gating and the listener opcodes gives a fully self-consistent channel map:

| type | registered on | listener (addr) | opcode it accepts | effective direction |
|---|---|---|---|---|
| **0** | master only | `DAT_0045efb8` | — | → R (unknown/startup) |
| **1** | **both** | `UserDataReplyListener @ 0x45b90c` | **9** | **bidirectional app data** |
| **2** | slave only | `DAT_0045efe0` | 1/3/5/0x10 | **R → L (display control)** |
| **3** | slave only | `SlaveInputEventReplyListener @ 0x45bbd4` | **7** | **R → L (input events)** |
| **4** | master only | `sched_recv_peer_sync_data @ 0x45ba68` | **0xC** | **L → R (sync data)** |

This is confirmed by the senders: type-2/3 builders gate on `lens_side()==1` (only R emits, L receives); `send_data_to_peer` (type 4) is called from `dashboard_ext_report_pb_state_to_peer` **only when `lens_side()==2`** (L emits, R receives); type 1 is registered on both ends so either lens can send.

All three data listeners call `FUN_004a827a(transport, …)` (TF ACK back to sender) **before** dispatching → **type 1 / 3 / 4 are reliable/acked**.

## 4. Opcode catalog (byte 1)

| opcode | primitive | msgType/type | wrapper addr |
|---|---|---|---|
| 1 | display **startup** | 2 | `request_display_startup @ 0x4642d6` |
| 3 | display **reflash** (present-forward) | 2 | `send_peer_app_cmd_op3 @ 0x46435a` |
| 5 | evenhub open | 2 | `evenhub_open @ 0x4643de` |
| 7 | **input event** to peers | 3 | `send_input_event_to_peers @ 0x464ef0` |
| 9 | **generic app data** | 1 | `send_app_command_to_peer @ 0x4644c4`, `SendDataToBothExt @ 0x46471e` |
| 0xC | **sync data** (L→R) | 4 | `send_data_to_peer @ 0x464c28`, `send_data_to_peer_noevent @ 0x464988` |
| 0xE | idle → schedule mgr | 5 | `SendIdleCommandtoScheduleManager @ 0x4652b8` (master only) |
| 0xF | startup → schedule mgr | 5 | `SendStartUpCommandtoScheduleManager @ 0x465524` (master only) |
| 0x10 | app ctrl | 2 | `send_peer_app_ctrl_op16 @ 0x464462` |

## 5. Async / scheduled variants (for aligned presents)

`sync.module.framework` exposes threadpool wrappers that **prepend a 4-byte "token" that is actually a delay in ms**, then re-emit the command after `FUN_00453a80(token)` (a delay):

- `AsyncRequestDisplayStartUp @ 0x45ac72` → cb `_AsyncStartUPApplicationDataHandlerCb @ 0x45ab8e` → `token=*data; delay(token); request_display_startup(id, data+1, len-4)` (opcode 1).
- `AsyncRequestDisplayReflash @ 0x45ae4e` → cb `_AsyncReflashApplicationDataHandlerCb @ 0x45ad6a` → `delay(token); send_peer_app_cmd_op3(id, data+1, len-4)` (opcode 3, **reflash-forward**).
- `AsyncSendInputEventToPeers @ 0x45b050` (0xE-byte packet: token, eventType@4, eventCode@6, eventValue@10) → cb `_AsyncSendInputEventToPeersDataHandlerCb @ 0x45af48` → `send_input_event_to_peers(...)`.

The **display-start barrier** used to make both eyes flip together lives here too:
- `DispStartBlockingEn @ 0x45c024` — **master-only** (`lens_side()==2 → returns 0xfffffffe`); takes a mutex, sets `*DAT_0045c378=1`, arms a timer capped at **15000 ms**. Blocks the master's present until the slave signals ready.
- `DispStartBlockingCancel @ 0x45c1f0` — releases the barrier (clears the flag, cancels timer).
- `DispStartBlocking_TimerCb @ 0x45bf8a` — timeout path, clears the flag.

## 6. Existing app practice — the common pattern

Every app that keeps R↔L state in sync uses the **same three-part recipe**: pick a stable **appID**, send a small struct whose **first byte is a sub-opcode**, and mirror it with a receiver that switches on that first byte.

| app (module) | send primitive | appID | packet shape (byte0 = sub-op) | dir / notes |
|---|---|---|---|---|
| onboarding.data_mgr — `RPC_OnboardingFlagSendToPeer @ 0x47af72` | `send_data_to_peer(0x10,…,ev=5)` | **0x10** | `{0x0D, flag}` (2B) | flag push |
| ″ `RPC_OnboardingFlagReplyToPeer @ 0x47afe8` | `send_data_to_peer(0x10,…,ev=5)` | 0x10 | `{0x0E, flag}` | **reply** to 0x0D |
| ″ `RPC_OnboardingProcessSyncToPeer @ 0x47b05a` | `send_data_to_peer(0x10,…,ev=5)` | 0x10 | `{0x09, a, b}` (3B) | state sync |
| dashboard.ext `dashboard_ext_report_pb_state_to_peer @ 0x525fbe` | `send_data_to_peer(0x1f,…,ev=5)` | **0x1f** | `{0x03, exists}` | **L→R** (`lens_side()==2` guard) |
| charger `CHG_SendBatteryInfoToPeer @ 0x4c5d2e` | `send_data_to_peer_noevent(0x105,…)` | **0x105** | `{reason, 0x08, side, …8B}` | telemetry, no-ack |
| ″ `CHG_ReceiveBatteryInfoFromPeer @ 0x4c5e42` | (receiver) | 0x105 | switch on `data[0]` (2/3) | reply→`CHG_SendBatteryInfoToPeer(2)` |
| ″ `CHG_RequestNotifyBatteryInfoFromPeer @ 0x4c5fcc` / `SVC_RingBattery_RequestFromPeer @ 0x5248f2` | `send_data_to_peer_noevent(0x105,…)` | 0x105 | `{0x04,…}` / `{0x06,…}` | request-notify |
| audio.mgr `AUDM_SendSyncMsgToPeer @ 0x56e404` | `send_data_to_peer_noevent(0x10c,…)` | **0x10c** | `{syncMsg}` (1B) | request→reply handshake |
| ″ `AUDM_HandlePeerSyncMsg @ 0x56e464` | (receiver) | 0x10c | switch on `syncMsg`, replies via `AUDM_SendSyncMsgToPeer` | ping-pong |
| box.detect `BoxDetect_ReceiveCaseInfoFromPeer @ 0x4c5182` | (receiver) | (case) | struct at `data[4..7]`, switch `data[0]==3` | reconcile+notify |

**The invariant pattern:**
1. **One appID per feature** (0x10, 0x1f, 0x105, 0x10c…).
2. **byte[0] of the payload = a private sub-opcode** (request / reply / notify), because the app-header opcode is fixed at 9 or 0xC by the wrapper.
3. **Request/reply is app-level**, not transport-level: a receiver handler switches on byte[0] and calls the *send* function again to answer (`0x0D→0x0E`, battery `req→send`, audio `syncMsg 1→2`).
4. `eventType=5` for RPC-style app messages; `send_data_to_peer_noevent` (event=0) for fire-and-forget telemetry.
5. Direction is a **property of the appID's role**, enforced by `lens_side()` guards in the sender (dashboard = L→R; input/display = R→L; battery = both poll).

## 7. Receive path & what a custom app must register

For **type 1 (opcode 9)** and **type 4 (opcode 0xC)**, the listener does:

```
SendUserDataToThreadPool(appID, payload+8, len, eventType)   // 0x45aab0
   → submit_work → _userDataHandlerCb (0x45aa54)
       → find_ui_DataHandler_by_id(appID, data, len, flags)   // registry dispatch
```

So a custom app **receives peer data by owning an entry in the UI-data-handler registry keyed by its appID** (the table `find_ui_DataHandler_by_id` walks). Register a fresh, unused appID (e.g. avoid 0x10/0x1f/0x105/0x10c) and every type-1 or type-4 frame carrying that appID is delivered to your callback as `(appID, data, len, flags=eventType)` on the threadpool. **No per-message listener registration is needed** — type-1/4 TF listeners already exist; you only slot into the appID demux.

Note the two other inbound channels do **not** use this registry:
- **type 2** (opcodes 1/3/5/0x10) is consumed by the **display/startup pipeline** on the slave (`request_display_startup` re-enters locally), not `find_ui_DataHandler_by_id`.
- **type 3** (opcode 7) is consumed by `SlaveInputEventReplyListener → FUN_00443cb8(type,code,value)`, the **input-event injector**.

## 8. Synthesis — what OUR custom app (running on both lenses) should call

`lens_side()` returns 1 on R/master, 2 on L/slave; branch your same binary on it. `get_sync_ctx @ 0x4657b8` returns the shared sync/TF context if you need the raw handle.

### (a) Push per-lens content R → L

| option | call | why / caveat |
|---|---|---|
| **✅ cleanest (app data)** | `send_app_command_to_peer(myAppID, buf, len, 0)` (`0x4644c4`, type 1/opcode 9) | Type 1 is registered on **both** lenses and dispatches straight to your appID handler; acked; works R→L (and L→R). Pure data, no display-pipeline side effects. |
| alt (richer demux) | `SendDataToBothExt(myAppID, buf, len, 0, subID)` (`0x46471e`) | Same wire (type 1/op 9) but also carries a **subID** in the eventType field → lets one appID fan out to sub-channels. |
| if you want it to drive the display pipe | `request_display_startup(myAppID, buf, len, 0)` (`0x4642d6`, type 2/op 1) | R→L only, feeds the slave's startup/display path — use only if you want the native display machinery, not raw bytes. |

Do **not** use `send_data_to_peer` for R→L — it's type 4, which only the **master** listens on (it's the L→R channel).

### (b) Trigger a synchronized present ("both eyes flip together")

The native mechanism is **push-then-barrier**, and the single most on-point primitive is the reflash-forward:

| step | call | note |
|---|---|---|
| **✅ cleanest present-forward** | `send_peer_app_cmd_op3(myAppID, frameOrCue, len, 0)` (`0x46435a`, type 2/opcode 3 = "reflash") | This is the exact op the native cross-lens sync uses (matches memory: "reflash-forward, two-phase present"). Master→slave. |
| scheduled/aligned variant | `AsyncRequestDisplayReflash(myAppID, data, len, delayMs)` (`0x45ae4e`) | Prepends `delayMs`; slave delays then reflashes — lets you dial in a fixed R/L skew. |
| **the actual "flip together" barrier** | master: `DispStartBlockingEn(timeoutMs)` (`0x45c024`) → wait for slave-ready → `DispStartBlockingCancel()` (`0x45c1f0`) | Master-only; blocks R's own present up to 15 s until L acks readiness, then both present. This is the firmware's built-in vsync-ish rendezvous. |

Practical recipe for our own-mode app: R sends the L frame via (a), then R sends `send_peer_app_cmd_op3` as the "present now" cue while R holds its own present behind `DispStartBlockingEn`; L, on receiving the cue, renders and signals ready (any type-1/4 message your appID interprets as "ready" → have R call `DispStartBlockingCancel`). This reproduces the native two-phase flip and is consistent with the ≤1-frame delta you already achieved with a self-built barrier — the firmware primitives (`DispStartBlockingEn/Cancel` + opcode-3 forward) are the native equivalent of that barrier.

### (c) Relay data L → R (e.g. a screenshot)

| option | call | why / caveat |
|---|---|---|
| **✅ cleanest (native L→R channel)** | `send_data_to_peer(myAppID, buf, len, 0, ev)` (`0x464c28`, type 4/opcode 0xC) | Type 4 is the channel the **master** listens on; this is exactly how `dashboard.ext` reports L→R. Acked. |
| fire-and-forget | `send_data_to_peer_noevent(myAppID, buf, len, 0)` (`0x464988`) | No eventType; used by battery telemetry. |
| symmetric alt | `send_app_command_to_peer` (type 1) | Also reaches R; use if you want one code path for both directions. |

**Screenshot caveat:** `post_app_command` enforces `len < 0x2800` (10 KB) per frame, and the UART/TinyFrame MTU applies to the type-4 path too. A full-panel screenshot must be **chunked** (put a chunk index in your payload byte[0]/subID and reassemble on R), mirroring how the apps put a sub-opcode in byte[0].

## 9. Honesty / open items

- **Type-4 in the R→L direction is unconfirmed.** Master clearly registers the type-4 listener; the slave's listener list was truncated in the dump right after types 2/3/1 (`TF_AddTypeListener((void *)*…`). Every observed use of `send_data_to_peer` is L→R, and R→L via type 4 is not demonstrated — so treat type 4 as **L→R only** and use type 1 for R→L until the slave's full registration table is dumped from `SyncModuleInit @ 0x45ec54`.
- **The registration API for the UI data handler** (the writer side of `find_ui_DataHandler_by_id`) is not in this 54-fn bundle. You need that symbol to actually bind `myAppID` → your callback; it lives in the UI/display module, not `sync.module.*`. Everything else needed to *send* is here and self-contained.
- **`ctx`** (descriptor +0) is a local reply-correlation pointer kept sender-side; it is **not** transmitted (only appID/subID/opcode go on the wire), so cross-lens reply matching must be done via your own subID/appID scheme, exactly as the onboarding `0x0D/0x0E` pair does.
- The type→TF-param table lookup inside `SyncModuleSendDataHandler` (the `DAT_0045ef58…ef88` cascade) was only partially decompiled; the type→direction conclusions above are derived from listener registration + sender `lens_side()` gating, which are unambiguous, not from that table.