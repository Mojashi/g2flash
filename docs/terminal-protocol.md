# Terminal mode — protocol RE notes

Even G2 (2.2.4.34) has a full on-device "terminal mode" (internal name; product-facing
name likely "EvenAI"/agent chat — see caveat below) with its own FSM, BLE protobuf
service, and LVGL screens (session list, query panel, ASR streaming, agent content).
This doc captures what's been confirmed via Ghidra RE of the stock firmware, aimed at
eventually driving/spoofing this protocol from an external ("hijacked") host — i.e. a
phone-side client that talks the SAME wire protocol the real Even AI backend/app would,
without needing any firmware changes.

`ghidra_addr = file_off + 0x39E680` (same DELTA as the rest of this repo's RE).

## ✅ SOLVED — confirmed working solution (Unicorn emulator + real hardware)

The terminal-mode hijack works end-to-end: an external BLE client drives the on-lens
agent UI (agent text renders on the physical glasses), no phone/host app needed. This
was nailed down by emulating the real firmware in Unicorn (scratchpad `g2emu.py` +
probes) and confirmed on hardware (incl. a printf-debug CFW streaming the internal FSM
over sid 0x7e — see `docs/terminal-debug-tool.md`).

**Wire frame (sid 0x30):** the outer protobuf is
`field1(tag1,varint)=DISCRIMINANT · field2(tag2,varint)=magic · field(DISC+2)(len-delim submsg)=payload`.
The dispatcher `FUN_005e5590` reads the **discriminant from decoded-struct offset 0**
(= field1's value) and passes the payload at offset 4. **field1 is the message
type/discriminant — NOT "magic". field2 is the magic/seq (the 3s-dedup key).** (Earlier
confusion: probes that put the counter in field1 were selecting the wrong action; e.g.
magic=4 accidentally ran session_status, magic=3 ran asr_result.)

**Discriminant → action** (verified by emulating the real dispatcher): `1`=mode_sync
`2`=host_status `3`=asr_result `4`=session_status `5`=agent_content `6`=query
`7`=error_msg `8`=session_list `9`=session_switch_result `10`=session_id_changed
`11`=new_session_result `0xff`=heart_beat. The oneof payload goes in wire tag `DISC+2`
(its submessage schema matches that action's struct).

**Confirmed sequence to render agent text on the lens** (each msg: field1=disc,
field2=increasing magic, payload in tag disc+2; space or vary to beat the 3s dedup):
1. `mode_sync{cmd=2}` → enter terminal mode (BOOTSTRAP→CLOSED)
2. `host_status{status=2}` → mark host "streaming" (**required**; without it the
   situation-classifier routes CLOSED→BLOCKED, a dead end)
3. `session_id_changed{id=S}` (S≠0) → establishes session, CLOSED/BLOCKED→IDLE
4. `session_status{status=1, id=S}` → IDLE→**AGENT_PROCESSING(7)** (the transition
   that must succeed; needs id==current session)
5. `agent_content{style, text, op=0, id, event, session_id=S}` → in state 7 fires
   CONTENT_APPEND(0x12) **and** CONTENT_BIND(0x13) → text binds and renders.
   `op` MUST be 0 or 2 (op=1 makes `classify_text_refresh` drop the text). `event=2`
   = streaming chunk, `event=4` = final.

**Why it renders (the "flush"):** text always appends to the content buffer
(`0x2010f256`) via event 0x12, but only **binds to the visible view via event 0x13**,
which `agent_content` fires **only when it observes `fsm_state==7` at RX time**. Reaching
and holding AGENT_PROCESSING(7) is the whole game; earlier "Waiting Input, no text" runs
never reached/held 7 so the bind (0x13) was dropped and text stayed unbound. Full render
mechanism: `RECONSTRUCTED_ui_render.md`.

**Tooling:** `demos/terminal-hijack.ts` (drive the sequence), `demos/terminal-debug.ts`
(drive + decode the sid-0x7e internal FSM trace, needs the debug CFW),
`docs/terminal-debug-tool.md` (how to use it), scratchpad `g2emu.py` + `map_dispatch2.py`
/ `decode_check.py` / `full_sequence.py` (the emulator that proved all of the above).

## TL;DR

- Terminal mode rides the **same aa21 envelope transport** as everything else in this
  firmware (see `g2flash.py`'s docstring) — no separate BLE service. Its own protobuf
  channel is **sid = 0x30** (confirmed: the input dispatcher's app-id gate compares the
  foreground-mode struct's id field against `0x30` for terminal-specific gesture
  handling — see [Push-gesture / app-id note](#push-gesture--app-id-note)).
- Messages are built/sent through **one shared encode function** (`FUN_005cf6dc` →
  `FUN_004a896a`) and validated/decoded through a **matching shared decode function**
  on RX (`FUN_005cf8a8` → `FUN_004aa2dc`). The decode loop's field-tag dispatch
  (`tag & 0xf == 10` → submessage/bytes, `tag & 0x30` → a 2-bit cardinality field)
  matches **nanopb's field-descriptor byte encoding** almost exactly — this is very
  likely a nanopb-derived embedded protobuf runtime, walking a real (not yet located)
  per-message field-descriptor array via `FUN_004fe436`/`FUN_004fe48a`/`FUN_004fe520`.
  ~~`DAT_005d00e0` is the shared schema descriptor~~ — **correction**: `DAT_005d00e0`
  turned out to be the base of a large **deferred-logging string cluster** (log format
  strings + their `[pb.terminal]`-prefixed variants + function-name strings), not a
  schema table. It happened to be referenced by the same functions coincidentally (as
  one of many log-string constants in their literal pools). The real schema pointer
  is still unlocated — next step would be decompiling `FUN_004fe436` directly.
- A **3-second duplicate-suppression window** is enforced on RX, keyed on the
  message's type byte: sending the identical message type twice within 3s gets
  **silently dropped** by the glasses. Any spoofing client must respect this (vary
  content or wait) or its second message vanishes with no error.
- Outbound (glasses→phone) terminal messages are only sent from **the lens where
  `FW_SIDE()==1`** (the "right" lens, in `zlib_glue.c`'s convention).

## Transport / framing

- Generic TX entry point: **`FUN_005cf6dc(msgId: u8, shape: u16, data: void*, seq: u8, wantAck: int)`**
  (ghidra `0x005cf6dc`). Builds a `[msgId][seq][shape_u16][...payload]` header into a
  fixed 0x850-byte scratch buffer (`DAT_005d00d8`), copies 0/1/2/3 words out of `data`
  depending on `shape` (see [shape table](#shape--field-count-table)), then:
  1. Copies a 20-byte envelope (`FUN_004a832c` + `FUN_00439c04`) and calls
     **`FUN_004a896a(header20, DAT_005d00e0 /* schema descriptor */, msgBuf)`** to
     serialize — this is the generic protobuf ENCODE, schema-driven.
  2. If `FW_SIDE()==1`: sends via `FUN_0047398c(1, 0x30, ptr, len)` (wantAck==0) or
     `FUN_00473a92(1, 0x30, ptr, len)` (wantAck!=0). **`FUN_0047398c` is the exact same
     send primitive `patches/settings_ext.c` already hooks** (`FW_SEND` /
     `bl FUN_0047398c` — the "aa21 send" the CFW patches redirect for the settings
     capability field). `sid=0x30` is the argument that selects the terminal channel.
- Generic RX validate/dedup gate: **`FUN_005cf8a8`** (= `APP_PbTerminalRxFrameDataProcess`).
  1. `FUN_004a98e0` + `FUN_00439c04` build a 16-byte header from the raw frame.
  2. **`FUN_004aa564(header16, DAT_005d00e0 /* same schema descriptor */, out)`** —
     generic protobuf DECODE into `out` (a persistent struct, `DAT_005e5720`).
  3. Dedup: `if (out.typeByte == last_type_byte && now - last_ts < 3000) return 0xd;`
     (0xd = REJECTED_DUPLICATE). Otherwise updates `last_type_byte`/`last_ts` and
     returns 0 (accepted), 5 (decode failed), or 6 (null args).
  - Caller **`FUN_005e5414`** wraps this: on 0xd/0/error it sets a status flag and
    calls `FUN_005cfa04(status, out.typeByte)` — this looks like the **CommResp
    ack-back** path (echoes an error code for the received message), not the actual
    business-logic dispatch.
  - **Not yet located**: the real per-opcode consumer (`terminal_action_agent_content`,
    `_asr_result`, `_query`, `_session_list`, etc.) that reads the decoded struct at
    `DAT_005e5720` and drives the FSM (`FUN_005e8b00`, see the mode-hijack doc/earlier
    thread). It's decoupled from the validate/ack step above — likely polled by the
    FSM's own task/thread rather than called synchronously from the RX path.

## Message ID table (confirmed)

TX (glasses → phone), from the `APP_PbTerminalTxEncode*` wrappers around `FUN_005cf6dc(msgId, shape, data, seq, wantAck)`:

| encoder name | msgId | shape (== real oneof tag, see below) |
|---|---|---|
| StatusReply | 0xa1 | 9 |
| VoiceInput | 0xa2 | 10 |
| QueryReply | 0xa3 | 11 (0xb) |
| AgentInterrupt | 0xa4 | 12 (0xc) |
| CommResp | 0xf0 | 13 (0xd) |
| SessionSwitchRequest | 0xa5 | 18 (0x12) |
| NewSessionRequest | 0xa6 | 19 (0x13) |
| DisplayStateNotify | 0xa7 | 20 (0x14) |
| NewSessionCancel | 0xa8 | 22 (0x16) |
| ListFocus | 0xa9 | 24 (0x18) |
| OverlayFocus | 0xaa | 25 (0x19) |

`msgId` (0xa1-0xaa, plus CommResp's outlier 0xf0) looks like a sequential
transport/BLE-level identifier, separate from the protobuf wire tag — **do not
confuse the two**. Field names/types for each (beyond the shared `magic`) are known
from the deferred-log string cluster at `DAT_005d00e0`: CommResp carries `err_code`;
StatusReply carries `current_mode, err_code`; SessionSwitchRequest carries
`host(u32), session(u32)`; NewSessionCancel carries nothing extra; DisplayStateNotify
carries `state, session(u32), overlay`; ListFocus carries `focused_index(u32)`;
OverlayFocus carries `overlay, focused_index(u32)`.

**Also confirmed from this log cluster**: the "3-second duplicate window" is keyed on
**`magic`** (`"terminal duplicate packet: magic=%d elapsed=%lu"`) — sending the same
`magic` twice within 3s gets silently dropped, so a spoofing client should increment
`magic` per message like every other pb channel in this firmware does.

### `shape` == the real protobuf oneof tag (verified, not guessed)

Traced the outer envelope's C struct layout directly from the schema (field data
offsets + the oneof "which" backoffset each field encodes — see
[The real schema](#the-real-schema-verified) below): **`magic` sits at struct offset
0, an unidentified second scalar at offset 1, and the `which_msg` oneof discriminant
at offset 2** — which is *exactly* where `FUN_005cf6dc` writes its `shape` parameter
(`*(short*)(buf+2) = shape`). This match was confirmed independently for **all 23**
oneof branches (every one computes the same offset-2 "which" address), not just one —
strong, structurally-verified evidence that **shape *is* which_msg *is* the wire tag**,
not a coincidental numeric overlap.

This resolves the tag for all 11 named encoders (table above). The `FUN_005cf6dc`
shape-based data-copy dispatch (9→1×u16, 10→1×u8, 0xb→2×u32, 0xc→1×u8, 0xd→1×u8,
0x12→2×u32, 0x13→1×u32, 0x14→3×u32, 0x16→1×u8, 0x18→1×u32, 0x19→2×u32) tells you how
many machine words of raw data each call packs — separate from, but indexed by, the
same tag value.

## Debug CLI simulator (documents the RX side for free)

The firmware ships a **debug console command set** (`terminal <subcommand>`) that
simulates INCOMING (phone→glasses) messages for testing without a real host. Its
usage strings double as free documentation of each RX message's fields:

```
terminal mode <0|1>                       - simulate mode sync (0=daily, 1=terminal)
terminal content <hi|dim> <add|rep> <t>   - simulate agent content (style + op + text)
terminal query <text> <cnt>               - simulate query with option 1..N
terminal query_reply <opt> [qid]          - simulate app-side query reply
terminal asr [text]                       - ASR interim chunk (sentence_final=0 all_final=0)
terminal asr_final [text]                 - all final chunk
terminal asr_sfinal [text]                - sentence final chunk
terminal err <0-2>                        - 0:success 1:fail 2:asr_failed
terminal host <0-2>                       - 0:no_host 1:offline 2:streaming
terminal status <0-4>                     - 0:none 1:thinking 2:await_user 3:done 4:reset
terminal new_result <0|1>                 - 0:success 1:failed
terminal switch_result <0|1>              - 0:success 1:failed
terminal session_changed <id>
terminal session_list <host> <cur> <cnt>  - ids are 1..cnt
terminal reset                            - SESSION_STATUS_RESET
terminal ble <0|1>                        - simulate ble callback
terminal cache                            - print cached data
```

**Tested live against real hardware (both arms) — this shortcut does NOT work.** The
firmware exposes a standard **Nordic UART Service** (`6E400001/2/3`, confirmed present
in the live GATT table on both L and R arms) and an **`AT^NUS=1` handshake that really
works** (glasses reply `NUS+OK`, matching the exact string embedded in the firmware).
But after that handshake, no `terminal <subcommand>` text (tried multiple line endings,
write-with/without-response, plus a full `mode 1` → `host 2` → `content` → `query`
activation sequence) produced any BLE reply *or* any visible effect on the lens.
Working hypothesis (unconfirmed): NUS is a **one-way debug-log visibility channel**
only — `AT^NUS=1` likely just enables *watching* logs over BLE, not *injecting*
commands — and the actual `terminal` debug shell is wired to a physical UART only, not
reachable wirelessly. This means there is **no shortcut**: hijacking terminal mode
requires implementing the real wire protocol above.

## Push-gesture / app-id note

Resolves an earlier open question from the mode/gesture investigation: the input
dispatcher (`FUN_004424a2`) gates long-press (subtype 3) behavior on the foreground
mode-context's app-id field (`*piVar6`): `0xe0` = EvenHub (patched by
`patches/gesture_fwd.c`), `3` = still unidentified, and **`0x30` = terminal mode**
(now confirmed, since terminal's own BLE channel is sid `0x30` — consistent numbering).
This is *why* the same gesture behaves differently per mode: EvenHub is special-cased
directly in the dispatcher, while terminal mode owns a large separate handler
(`terminal_input_event_handler` / `FUN_005e82b0`) that reinterprets the same posted
event codes (0x44/0x45 continuous move, 0x48, 8, 10, ...) against its own FSM state.

## Live hardware validation (real success, not just static RE)

Built a minimal protobuf encoder (`demos/terminal-probe.ts`) from the reconstructed
schema above and tested it against **real G2 hardware** over `sid=0x30`, for each of
the 12 oneof tags not accounted for by the 11 known TX (outbound) encoders
(candidates: 3,4,5,6,7,8,14,15,16,17,21,23), sending `outer{magic=N, tag=T{1:VALUE}}`.

**Result: tag=3 is real.** It's the only candidate that got any response at all — a
genuine `sid=0x30` reply frame, structured as `{f1=0xa1, f2=1, f9={1:ECHO}}`. All 11
other candidates timed out silently (rejected or unhandled).

Re-tested tag=3 with `VALUE` = 0,1,2,3 and found the echoed field (f9's inner value)
follows **`(VALUE==2) ? 2 : 1`** exactly — a genuine conditional branch in the
firmware, live, driven by a message built entirely from static reverse engineering.
This matches the shape of `terminal_action_mode_sync`'s own logic (special-cases
`*param_1 == 2` specifically).

**CONFIRMED on real hardware**: sending tag=3 with value=2 (`08 01 1a 02 08 02` +
outer magic) **actually switched the HUD into terminal mode, visibly, on the physical
glasses.** Tag 3 = `terminal_action_mode_sync` (event index 0 in the
0x0072b178 action table). This is a fully closed loop: static RE of the stock
firmware → reconstructed wire schema → hand-built protobuf bytes → sent over BLE →
real, visible mode change on the device. **Terminal mode can be entered from an
external client without any firmware modification, by sending
`outer{magic, tag3{1: 2}}` on sid=0x30.**

This is the first end-to-end validation of the whole reconstruction: envelope
structure (magic@0, which_msg@2), the `shape`==tag finding, and the sid=0x30
transport all check out against a real device, not just decompiler output.

Retested all 12 candidates again while terminal mode was already active (in case
query/agent_content-type actions were previously no-oping due to being in the wrong
FSM state) — still only tag=3 responds. Most likely explanation: the test payload
(a single varint byte) only matches tag=3/mode_sync's real field shape; tags whose
real messages carry a **string** (agent content text, query text) would see a
wire-type mismatch against a varint test field and fail to decode silently — this is
expected, not evidence those tags are dead. Confirming them needs a test payload
shaped like their real fields (e.g. a length-delimited string), not more 1-byte probes.

## Open questions / next steps

1. ~~Find the real per-message field-descriptor table~~ — **DONE** (outer envelope:
   magic@0, unidentified scalar@1, which_msg/tag@2 — verified across all 23 branches).
2. **Redo the per-tag sub-message field walk correctly** — the first attempt likely
   desynced on field width (see the correction above). Needs either careful
   per-field width verification (don't assume `atype`==1 for submessage fields) or
   decompiling `FUN_004a8930`'s own descriptor-lookup logic directly.
3. **Locate the async consumer of `DAT_005e5720`** (the decoded-RX-struct buffer) —
   this is where `terminal_action_*` (query/session_list/agent_content/...) actually
   fires.
4. **Name the remaining ~12 unnamed oneof tags** — blocked on #2.
5. **Confirm LTYPE 0x6's exact wire type** (STRING vs BYTES) empirically — matters for
   encoding any text-carrying field (agent content, query text). Also blocked on #2.

## The real schema (verified)

Found by correctly tracing the pointer chain (an earlier attempt misidentified
`DAT_005d00e0` itself as a string table — see the correction above; the fix was
reading `DAT_005d00e0`'s **own 4-byte value**, not iterating past it as an array):

```
DAT_005d00e0 (a single pointer variable) = 0x00777840
  -> pb_msgdesc_t-shaped struct: {fields_array_ptr, ptrB, 0, 0, field_count, field_count}
     fields_array_ptr = 0x006ce174, field_count = 25   (the OUTER envelope message)
```

Immediately following this struct, in the SAME rodata section, is an **array of 25
more identically-shaped 24-byte structs** (`0x00777840 + N*0x18` for N=1..25) — one
per oneof branch — each with its own `fields_array_ptr` + `field_count`. This is a
real, verified nanopb-style compact field-descriptor engine: each field is a
variable-width (1/2/4/8 word) record whose first word packs `atype` (low 2 bits,
selects record width), `ltype`+`htype` (byte 1), and part of the wire tag; `FUN_004fe4aa`
(confirmed as the function the decode loop actually calls to seek a field by its real
wire tag) was decompiled to get the *exact* tag-assembly bit formula — not guessed.

**Outer envelope** (`ghidra 0x006ce174`, 25 fields):

| tag | ltype | htype | meaning |
|-----|-------|-------|---------|
| 1   | 0x2 (uvarint) | 1 | likely `magic` (every terminal msg's log line has `magic=%d`) |
| 2   | 0x2 (uvarint) | 1 | unidentified second scalar (a `cmd`/dispatch-type discriminant?) |
| 3–25 | 0x8 (submessage) | 3 (**oneof**) | the 23 terminal message variants (one field per message type) |

### Per-tag sub-message fields — RESOLVED (subagent reconstruction, 2026-07)

The earlier "not yet reliably resolved" walk (below, kept for history) had a real
bug: it assumed `entry_index == tag` or `tag-2`. Two parallel subagents rebuilt this
from scratch by decompiling the actual field-descriptor engine
(`FUN_004fe220`/`FUN_004fe436`/`FUN_004fe3bc`/`FUN_004fe48a`) instead of guessing at
raw words, and cross-validated the result against **real spontaneous device traffic**
(a captured `DisplayStateNotify` frame matched the reconstructed schema byte-for-byte).
Full write-up: `RECONSTRUCTED_tx_schema.md` / `RECONSTRUCTED_rx_dispatch.md` in the
investigation scratchpad.

**The real linkage**: submessage-typed fields (`ltype` 8/9) index into the schema's
`ptrB` pointer array using a **running counter of submessage fields seen so far
during iteration** — not tag arithmetic, not array index. This is why the old walk
desynced: it silently miscounted after field 1.

**Confirmed tag → submessage shape table** (local tags restart at 1 inside each
branch, as normal for protobuf submessages):

| Wire tag | Own fields | Best-fit RX action (CLI arg match) |
|---|---|---|
| 3 | f1:u1B, f2:u1B | **mode_sync** (CONFIRMED live: value=2 switches to terminal mode) |
| 4 | f1:u1B, f2:u1B | host_status? (`host <0-2>`, single visible arg + shape has 2) |
| 5 | f1:u1B, f2:u1B, f3:BYTES~514B | asr_result? (`asr/asr_final/asr_sfinal [text]` — 2 flags + text) |
| 6 | f1:u1B, f2:u4B | session_status? (`status <0-4>` — status enum + session id) |
| 7 | f1:u1B, f2:BYTES~514B, f3:u1B, f4:u4B, f5:u1B, f6:u4B | **agent_content** — matches the RX struct field order (style, text, op, id, event, session_id) field-for-field |
| 8 | f1:u4B, f2:BYTES~1026B, f3:REPEATED submsg×8 {id:u32,label:bytes[130]}, f4:u4B | **query** (`query <text> <cnt>` — query_id + text + up to 8 options + a flag) |
| 9,10,11,12,13 | (known — StatusReply/VoiceInput/QueryReply/AgentInterrupt/CommResp, TX-only) | — |
| 14 | *(empty, 0 fields)* | reset? (`reset` → SESSION_STATUS_RESET, no payload needed) |
| 15,17,23 | f1:u1B each | 3 simple 1-arg actions: error_msg / session_switch_result / new_session_result (`err<0-2>` / `switch_result<0|1>` / `new_result<0|1>`), exact assignment among these 3 unconfirmed |
| 16 | f1:u4B, f2:u4B, f3:REPEATED submsg×10 {id:u32,label:bytes[130],flag:u8} | **session_list** (`session_list <host> <cur> <cnt>` — host + current + id list) |
| 18,19,20,22,24,25 | (known — SessionSwitchRequest/NewSessionRequest/DisplayStateNotify/NewSessionCancel/ListFocus/OverlayFocus, TX-only) | — |
| 21 | f1:u4B | **session_id_changed** (`session_changed <id>` — single id, needs 4B not 1B) |

**Reconciling the RX-dispatch discriminant with the wire tag**: a separate subagent
traced the actual per-action dispatcher (`FUN_005e5590`/`FUN_005eaef4`, table at
`0x0072b174`) and found it switches on a compact **discriminant byte 1–11**
(mode_sync=1, host_status=2, asr_result=3, session_status=4, agent_content=5, query=6,
error_msg=7, session_list=8, session_switch_result=9, session_id_changed=10,
new_session_result=11), and reported this discriminant looked like "the raw wire tag,
verbatim, no offset" — which directly contradicted the hardware-confirmed fact that
wire tag **3** (not 1) triggers mode_sync. Cross-checking against the table above
resolves it: **`wire_tag = discriminant + 2` holds cleanly for discriminants 1–6**
(3,4,5,6,7,8 — all six shapes above are structurally consistent with their guessed
action), then **breaks into a non-sequential assignment for discriminants 7–11**
(landing on 15/16/17/21/23 rather than 9/10/11/12/13, which are already taken by the
TX-only messages). The subagent's "no offset" conclusion was an artifact of not
tracing all the way back to the outer envelope's own tag assignment — the discriminant
byte it saw is written into the RX-decoded struct *after* the outer oneof has already
resolved the wire tag to an action, so "no offset" was only ever true for *its own*
internal indexing, not for the wire tag itself.

**Practical consequence**: my earlier failed `agent-content-probe.ts` attempts (tag=7,
3-field guesses: style/op/text in various orders) were reaching the *right* wire tag
but the *wrong* field layout — the real submessage has **6** fields (style, text, op,
id, event, session_id), not 3. A corrected probe using the exact 6-field layout (with
id/event/session_id sent as 0 and omitted per proto3 implicit-presence) is the next
concrete test — see `demos/agent-content-probe2.ts`.

<details><summary>Original (buggy) walk attempt — kept for history</summary>

An attempt to find, for each oneof tag, which of the 25 sibling 24-byte descriptor
structs (`0x00777840 + N*0x18`) holds *that* tag's own field list produced
**inconsistent results** (multiple tags appeared to point at the same struct; a
"which-array-index" 12-bit value extracted from each outer field's second word gave
implausible out-of-range indices for several tags). The likely cause: submessage/oneof
fields probably need a **wider descriptor record** than the 2-word (`atype`==1) width
this investigation assumed for all 23 branches — if the true width is 4 or 8 words for
these specific fields, the array walk silently desyncs after the first submessage
field, and everything read past that point is unreliable.

</details>

## Open questions / next steps (updated)

1. ~~Redo the per-tag sub-message field walk~~ — **DONE**, see table above.
2. **Test the corrected agent_content layout (tag=7, 6 fields) live.** Highest-value
   next step — this is the actual "inject chat content" hijack primitive.
3. **Test query (tag=8, 4 fields) live** — the other high-value primitive (trigger a
   query notification with custom text/options).
4. **Confirm host_status (tag=4)** — may be required to escape the "waiting for host"
   idle state the glasses fall back into after a timeout (matches user's live
   observation of needing "a further phase of connecting to terminal").
5. Pin down the exact assignment among tags 15/17/23 → {error_msg, session_switch_result,
   new_session_result} — low priority, all three are simple single-byte-result acks.
6. Confirm LTYPE 0x6 vs 0x7 (BYTES vs STRING) empirically for the text-carrying fields —
   doesn't affect wire bytes (both are length-delimited/wiretype 2) but matters if the
   firmware validates UTF-8 specifically.
7. Check whether the FSM reconstruction (in progress) reveals what actually satisfies
   "waiting for host" — may make host_status unnecessary if it's driven by something
   else (e.g. a BLE-connection-level event rather than a pb message).
