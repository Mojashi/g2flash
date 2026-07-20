#!/usr/bin/env bun
// The FSM reconstruction (RECONSTRUCTED_fsm.md) found the exact gate that keeps
// terminal mode stuck at "waiting for host": right after mode_sync, the UI FSM
// lands in CLOSED(state 1), which has NO voice_start handler registered at all.
// The ONLY way out is event 35 = SESSION_ID_CHANGED -> terminal_ui_action_session_id_changed
// -> (usually) IDLE(state 2), which is the first state where voice_start works.
//
// Per docs/terminal-protocol.md's reconciled RX schema table, session_id_changed
// is RX discriminant=10, wire tag=21, single field f1 = session id (u32, non-zero
// or it's implicit-presence-omitted).
//
// Sequence: mode_sync(tag3, value=2) to (re)enter terminal mode, then
// session_id_changed(tag21, id=1) to try to unblock CLOSED -> IDLE.
// WATCH THE LENS while this runs -- a real state change here should be visible
// (the "waiting for host" prompt should change, or voice_start should start
// working via gesture).
//
//   bun session-id-changed-probe.ts [id]

import { G2Session } from "g2-kit/ble";

function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }
function varint(n: number): number[] {
  const out: number[] = [];
  let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function varField(f: number, v: number): number[] {
  if (v === 0) return [];
  return [...tagByte(f, 0), ...varint(v)];
}
function wrapOuter(magic: number, tag: number, submsg: number[]): Uint8Array {
  return new Uint8Array([...tagByte(1, 0), ...varint(magic), ...tagByte(tag, 2), ...varint(submsg.length), ...submsg]);
}

const SESSION_ID = process.argv[2] ? Number(process.argv[2]) : 1;

console.log(`[sid-changed] target session id = ${SESSION_ID}`);
const session = await G2Session.open();
console.log(`[sid-changed] connected.`);

session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  const hex = Buffer.from(frame.pb).toString("hex");
  const tagStr = frame.sid === 0x30 ? "  <-- TERMINAL" : "";
  console.log(`[${ts()}] ${arm} sid=0x${frame.sid.toString(16)} flag=0x${frame.flag.toString(16)} pb=${hex}${tagStr}`);
});

let magic = 300; // fresh range, never reused

// Step 1: (re)enter terminal mode -- confirmed working trigger.
{
  const sub = [...tagByte(1, 0), ...varint(2)];
  const pb = wrapOuter(magic, 3, sub);
  console.log(`\n[sid-changed] >>> mode_sync(value=2)  magic=${magic}  bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[sid-changed] ack: ${Buffer.from(ack.pb).toString("hex")}` : "[sid-changed] no direct ack");
  magic++;
}
console.log("[sid-changed] waiting 4s, check the lens now (should be in/entering terminal mode)...");
await new Promise((r) => setTimeout(r, 4000));

// Step 2: fire SESSION_ID_CHANGED (tag=21) with a nonzero id.
{
  const sub = [...varField(1, SESSION_ID)];
  const pb = wrapOuter(magic, 21, sub);
  console.log(`\n[sid-changed] >>> session_id_changed(id=${SESSION_ID})  magic=${magic}  bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[sid-changed] ack: ${Buffer.from(ack.pb).toString("hex")}` : "[sid-changed] no direct ack -- watching for async traffic...");
  magic++;
}

console.log("\n[sid-changed] watching 6s for any follow-up traffic. CHECK THE LENS for a visible state change...");
await new Promise((r) => setTimeout(r, 6000));
await session.close();
process.exit(0);
