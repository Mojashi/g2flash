#!/usr/bin/env bun
// Corrected agent_content + query probe, built from the subagent-reconstructed
// schema (docs/terminal-protocol.md, "Per-tag sub-message fields — RESOLVED").
//
// Earlier agent-content-probe.ts guessed WRONG field layouts for tag=7 (3-field
// style/op/text in various orders) -- the real submessage has 6 fields in a
// fixed wire order: f1=style, f2=text(BYTES), f3=op, f4=id, f5=event,
// f6=session_id. This script sends the corrected layout (minimal 3-field version
// first, then a full 6-field version with nonzero id/event/session_id), plus a
// query (tag=8) candidate and a host_status (tag=4) candidate.
//
// Single BLE session for send+listen. Watch the physical lens while this runs.
//
//   bun agent-content-probe2.ts

import { G2Session } from "g2-kit/ble";

function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }
function varint(n: number): number[] {
  const out: number[] = [];
  let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function strField(f: number, s: string): number[] {
  const b = [...Buffer.from(s, "utf8")];
  return [...tagByte(f, 2), ...varint(b.length), ...b];
}
function varField(f: number, v: number): number[] {
  if (v === 0) return []; // proto3 implicit presence: zero is omitted from the wire
  return [...tagByte(f, 0), ...varint(v)];
}
function wrapOuter(magic: number, tag: number, submsg: number[]): Uint8Array {
  return new Uint8Array([...tagByte(1, 0), ...varint(magic), ...tagByte(tag, 2), ...varint(submsg.length), ...submsg]);
}

const TEXT = "hijack test";

const CANDIDATES: Array<{ desc: string; tag: number; submsg: number[] }> = [
  {
    desc: "agent_content minimal: tag7{f1:style=1(hi), f2:text, f3:op=2(rep)}",
    tag: 7,
    submsg: [...varField(1, 1), ...strField(2, TEXT), ...varField(3, 2)],
  },
  {
    desc: "agent_content full: tag7{f1:style=1, f2:text, f3:op=2, f4:id=1, f5:event=1, f6:session_id=1}",
    tag: 7,
    submsg: [...varField(1, 1), ...strField(2, TEXT), ...varField(3, 2), ...varField(4, 1), ...varField(5, 1), ...varField(6, 1)],
  },
  {
    desc: "query minimal: tag8{f1:query_id=42, f2:text}",
    tag: 8,
    submsg: [...varField(1, 42), ...strField(2, "test query")],
  },
  {
    desc: "host_status candidate: tag4{f1:2, f2:1}",
    tag: 4,
    submsg: [...varField(1, 2), ...varField(2, 1)],
  },
];

console.log(`[acp2] ${CANDIDATES.length} corrected candidates`);
const session = await G2Session.open();
console.log(`[acp2] connected.`);

session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  const hex = Buffer.from(frame.pb).toString("hex");
  const tagStr = frame.sid === 0x30 ? "  <-- TERMINAL" : "";
  console.log(`[${ts()}] ${arm} sid=0x${frame.sid.toString(16)} flag=0x${frame.flag.toString(16)} pb=${hex}${tagStr}`);
});

let magic = 200; // fresh range, never reused across any earlier script in this session

// Ensure terminal mode is actually active first -- CONFIRMED trigger from earlier
// live testing (docs/terminal-protocol.md). Without this, the FSM may not be in a
// state that accepts agent_content/query/host_status at all, which would explain
// a generic CommResp{errCode=1} rejection regardless of payload correctness.
{
  const enterSub = [...tagByte(1, 0), ...varint(2)]; // tag3{f1=2}
  const pb = wrapOuter(magic, 3, enterSub);
  console.log(`\n[acp2] >>> MODE_SYNC_ENTER (ensure terminal mode active)  magic=${magic}  bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[acp2] direct ack: pb=${Buffer.from(ack.pb).toString("hex")}` : `[acp2] no direct ack`);
  await new Promise((r) => setTimeout(r, 3500));
  magic++;
}

for (const c of CANDIDATES) {
  const pb = wrapOuter(magic, c.tag, c.submsg);
  console.log(`\n[acp2] >>> ${c.desc}  magic=${magic}  bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[acp2] direct ack: pb=${Buffer.from(ack.pb).toString("hex")}` : `[acp2] no direct ack -- watching 3s for async traffic / check the lens...`);
  await new Promise((r) => setTimeout(r, 3500)); // > 3s dedup window
  magic++;
}

console.log("\n[acp2] done. Watching 5s more for trailing traffic...");
await new Promise((r) => setTimeout(r, 5000));
await session.close();
process.exit(0);
