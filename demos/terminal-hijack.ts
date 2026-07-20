#!/usr/bin/env bun
// Terminal-mode hijack sequence, rebuilt from Unicorn emulation of the real firmware
// (scratchpad/g2emu.py + probes). KEY CORRECTION over every earlier probe script:
//
//   The outer protobuf's field1 (tag1) is the *message TYPE / discriminant*, NOT "magic".
//   field2 (tag2) is the msgSeq/magic (dedup key). fields 3..25 are the oneof payload.
//   The dispatcher (FUN_005e5590) selects the action purely from field1's value:
//     1=mode_sync 2=host_status 3=asr_result 4=session_status 5=agent_content
//     6=query 7=error_msg 8=session_list 9=session_switch_result 10=session_id_changed
//     11=new_session_result 0xff=heart_beat
//   The matching oneof payload for action D goes in field(D+2) (its submessage schema
//   matches that action's struct). All of this was verified by decoding these exact
//   bytes through the firmware's real decoder in emulation (all rc=0 accepted).
//
// Emulated happy-path to get from cold terminal mode to rendered agent text:
//   1. mode_sync(mode=2)            enter terminal mode                (-> CLOSED)
//   2. host_status(status=2)        mark host "streaming"  *** the missing step ***
//   3. session_id_changed(id=1)     promote session 1; classify=streaming -> CLOSED->IDLE
//   4. session_status(status=1)     thinking; id matches -> IDLE->AGENT_PROCESSING
//   5. agent_content(text=...)      fsm_state==7 -> render content
//
// Stays connected the whole time. WATCH THE LENS at each step.
//   bun terminal-hijack.ts                 # full sequence
//   bun terminal-hijack.ts 3               # stop after step N (1..5)

import { G2Session } from "g2-kit/ble";

function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }
function varint(n: number): number[] {
  const out: number[] = []; let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function vfield(f: number, v: number): number[] { return [...tagByte(f, 0), ...varint(v)]; }
function bfield(f: number, data: number[]): number[] { return [...tagByte(f, 2), ...varint(data.length), ...data]; }
function strbytes(s: string): number[] { return [...Buffer.from(s, "utf8")]; }

// build outer frame: field1=disc, field2=magic, field(disc+2)=submessage(payload)
function build(disc: number, magic: number, payload: number[]): Uint8Array {
  return new Uint8Array([...vfield(1, disc), ...vfield(2, magic), ...bfield(disc + 2, payload)]);
}

const STOP_AFTER = process.argv[2] ? Number(process.argv[2]) : 5;
const TEXT = process.argv[3] ?? "HELLO from external host";

type Step = { n: number; name: string; disc: number; payload: number[]; note: string };
const STEPS: Step[] = [
  { n: 1, name: "mode_sync(mode=2)", disc: 1, payload: vfield(1, 2),
    note: "enter terminal mode" },
  { n: 2, name: "host_status(status=2 streaming)", disc: 2, payload: vfield(1, 2),
    note: "mark host connected/streaming -- unblocks CLOSED" },
  { n: 3, name: "session_id_changed(id=1)", disc: 10, payload: vfield(1, 1),
    note: "promote session 1 -> expect CLOSED->IDLE ('Waiting Input')" },
  { n: 4, name: "session_status(status=1 thinking, id=1)", disc: 4, payload: [...vfield(1, 1), ...vfield(2, 1)],
    note: "expect IDLE->AGENT_PROCESSING ('thinking'/spinner)" },
  // op MUST be 0 (add) or 2 -- op=1 makes classify_text_refresh return 0 and the text is
  // dropped (verified in emulation). event=2 = streaming chunk (stays in processing);
  // event=4 = final. We stream chunks (event=2) then finalize (event=4) below, so the
  // rendered text sticks instead of ending the turn immediately.
];

// agent_content builder: style=1, text, op=0(add), id=1, event, session_id=1
function contentPayload(text: string, event: number): number[] {
  return [...vfield(1, 1), ...bfield(2, strbytes(text)), ...vfield(3, 0),
          ...vfield(4, 1), ...vfield(5, event), ...vfield(6, 1)];
}

const session = await G2Session.open();
console.log(`[hijack] connected. Will run steps 1..${STOP_AFTER}. WATCH THE LENS.`);
session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok || frame.sid !== 0x30) return;
  console.log(`[${ts()}]   <-- TERMINAL sid=0x30 flag=0x${frame.flag.toString(16)} pb=${Buffer.from(frame.pb).toString("hex")}`);
});

let magic = 100; // field2/dedup + ack key; monotonic, never reused

// Software reset: leave terminal mode (mode_sync with cmd != 2) to force the terminal
// UI FSM back to a clean BOOTSTRAP state, then re-enter below. Avoids needing a physical
// power-cycle -- clears any stuck/dirty state left by earlier runs.
{
  const pb = build(1, magic, vfield(1, 0)); // mode_sync cmd=0 -> leave terminal mode
  console.log(`\n[hijack] === Reset: leave terminal mode (mode_sync cmd=0) ===`);
  console.log(`[hijack]   returning to a clean state before re-entering...`);
  await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 2000 });
  magic++;
  await new Promise((r) => setTimeout(r, 2500));
}

async function send(disc: number, payload: number[], label: string, note: string) {
  const pb = build(disc, magic, payload);
  console.log(`\n[hijack] === ${label} ===`);
  if (note) console.log(`[hijack]   ${note}`);
  console.log(`[hijack]   field1(disc)=${disc} field2(magic)=${magic}  bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 2000 });
  console.log(ack
    ? `[hijack]   CommResp: pb=${Buffer.from(ack.pb).toString("hex")}  (...6a00 = errCode=0 success)`
    : `[hijack]   no direct ack`);
  magic++;
}

// Setup steps (tight 1.5s gaps so AGENT_PROCESSING doesn't time out before content)
for (const step of STEPS) {
  if (step.n > STOP_AFTER) break;
  await send(step.disc, step.payload, `Step ${step.n}: ${step.name}`, step.note);
  console.log(`[hijack]   waiting 1.5s -- watch the lens...`);
  await new Promise((r) => setTimeout(r, 1500));
}

if (STOP_AFTER >= 4) {
  // Stream agent content chunks fast (event=2), then finalize (event=4). This is the
  // "hijack": drive the on-lens agent text from an external client.
  const chunks = [TEXT + " ", "-- line 2 -- ", "streamed from macOS."];
  let acc = "";
  for (const c of chunks) {
    acc += c;
    await send(5, contentPayload(acc, 2), "agent_content chunk (event=2 stream)",
               `text so far: "${acc}"`);
    await new Promise((r) => setTimeout(r, 900));
  }
  await send(5, contentPayload(acc, 4), "agent_content FINAL (event=4)",
             "finalize -- text should stay on lens");
}

console.log("\n[hijack] done. Staying connected 20s -- CHECK THE LENS for the streamed text...");
await new Promise((r) => setTimeout(r, 20000));
await session.close();
process.exit(0);
