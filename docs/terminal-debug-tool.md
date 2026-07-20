# Terminal-mode debug tool — how to use it

A workflow for watching the G2 terminal-mode UI state machine **live on real
hardware**: a debug custom firmware that streams the firmware's internal FSM
state over BLE, plus a client script that drives the terminal-mode "hijack"
sequence and decodes that stream.

This is what let us confirm, from inside the firmware, exactly why injected agent
text does / doesn't render (see the working run at the bottom).

## Pieces

| Piece | What it is |
|---|---|
| `patches/dbg_terminal.c` + `patches/DEBUG_CFW.md` | the debug CFW: 3 length-preserving `bl` hooks that emit 14-byte records on **sid `0x7e`** (magic `0xE7`) for every FSM transition and every UI-event enqueue. Superset of the display CFW (includes all image/display mods too). |
| `demos/terminal-debug.ts` | client: drives the full hijack sequence on sid `0x30` **and** decodes the sid `0x7e` debug records into readable `«FW»` lines. |

## 1. Build + flash the debug CFW (one time)

```bash
cd g2flash
# restore/produce the debug patch set (23 patches = 20 display + 3 debug hooks)
python3 patches/apply_patches.py g2_2.2.4.34.bin patches/cfw_patches.json g2_2.2.4.34_cfw.bin
shasum -a 256 g2_2.2.4.34_cfw.bin   # expect 66f205100e6c709a03f8dc606569778fb14cc4cb0b1a18273a3a402f939edf45

# flash both lenses (phone Bluetooth OFF; glasses worn/awake, out of the case, near the Mac)
PYTHONUNBUFFERED=1 ./venv/bin/python g2flash.py \
  -c 'g2://local?left=00:00:00:C8:A2:31&right=00:00:00:20:5E:E2&addressType=public' \
  -f g2_2.2.4.34_cfw.bin --my-warranty-is-void
```

Notes (from flashing 2026-07):
- `PYTHONUNBUFFERED=1` is what makes block-by-block progress show up live (otherwise
  Python buffers all stdout until the process exits and the log looks frozen).
- The arm addresses are matched by the **last 3 MAC bytes in the advertised name**
  (`Even G2_32_L_C8A231` → `00:00:00:C8:A2:31`). Re-scan if your arms differ.
- If it flashes one lens then can't find the other, re-run with `--lens left|right`.
- After flashing you may need to force a reboot: tap **both touchpads 10×** (slight beep).
- Do **not** reconnect the official Even app — it upgrades to 2.2.5.10 and wipes the mod
  (which is also the convenient uninstall path).
- The debug hooks are in terminal-UI (non-boot) code paths; the bootloader is untouched,
  so a hook bug can only crash terminal mode, not prevent boot.

## 2. Run the debug session

```bash
cd g2flash/demos
bun terminal-debug.ts "your text here"
```

It connects, then: `reset → mode_sync(enter) → host_status(streaming) →
session_id_changed → session_status(thinking) → agent_content ×3 chunks`, and
prints both the sid-0x30 replies and the sid-0x7e `«FW»` internal records.

## 3. Reading the output

Two record types (both decoded automatically):

```
«FW» POST  [state seen: IDLE] enqueue SESSION_STATUS_UPDATE  arg=1 tick=111341
«FW» FSM   IDLE --SESSION_STATUS_UPDATE--> AGENT_PROCESSING   arg=1 tick=111345
```

- **`POST`** (rec_type 2) — the RX task enqueued a UI event; `state seen` is the live
  `fsm_state` the poster observed at that instant. This is how you catch the RX/UI race
  (e.g. an `agent_content` posting `CONTENT_APPEND` while it still sees `IDLE`).
- **`FSM`** (rec_type 1) — the UI task's actual transition `old --event--> new`.
- `tick` is the firmware ms tick — sort POST + FSM by tick to see the true ordering.

Raw wire format (sid `0x7e`, 14 bytes LE): `[E7][rec_type][state_a][event_id][state_b][00][arg u32][tick u32]`.

State ids: `0`BOOTSTRAP `1`CLOSED `2`IDLE `3`BLOCKED `4`VOICE_CAPTURING
`5`ASR_STREAMING `6`ASR_FINAL `7`AGENT_PROCESSING `8`AGENT_INTERRUPT_CONFIRM
`9`QUERY_PENDING `10`QUERY_NOTIFICATION `11`SESSION_LIST `12`NEW_SESSION_PENDING.

Key events: `1`DISPLAY_ENTER `15`SESSION_STATUS_UPDATE `16`AGENT_DONE `17`AGENT_RESET
**`18`(0x12) CONTENT_APPEND** **`19`(0x13) CONTENT_BIND** `35`SESSION_ID_CHANGED.
(Full legend in `demos/terminal-debug.ts` and `patches/DEBUG_CFW.md`.)

## 4. The key insight it proved (working run, 2026-07)

Agent text renders **only** when `agent_content` fires `CONTENT_BIND(0x13)`, and
`0x13` fires **only while `fsm_state == AGENT_PROCESSING(7)`**. The successful run:

```
mode_sync          : BOOTSTRAP → CLOSED
                     CLOSED → BLOCKED            (transient)
session_id_changed : BLOCKED → IDLE             (session established)
session_status     : IDLE → AGENT_PROCESSING    (the transition that used to fail)
agent_content ×3   : in AGENT_PROCESSING, each fires CONTENT_APPEND(0x12)
                     AND CONTENT_BIND(0x13)      → text binds → 3 lines on the lens
```

Earlier "Waiting Input, no text" runs were the FSM not reaching/holding state 7, so
`0x13` was dropped and the text stayed in the buffer unbound. A clean reboot + the
`reset → re-enter` prefix + correct field values fixed it. The `«FW»` stream is how
you tell "reached 7 and bound" from "dropped the bind" at a glance.
