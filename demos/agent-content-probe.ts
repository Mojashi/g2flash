#!/usr/bin/env bun
// Try to construct a real "agent content" message (wire tag=7, per the confirmed
// dispatcher: discriminant byte 5 -> terminal_action_agent_content, struct size
// 0x214 -- and byte = wire_tag - 2, so wire_tag=7). Matches the debug CLI's
// `terminal content <hi|dim> <add|rep> <t>` (style, op, text). Inner field
// numbers for the submessage are NOT confirmed -- this tries a few plausible
// layouts and reports the response for each so we can see which (if any) the
// firmware accepts (errCode=0) vs rejects (errCode=1).
//
//   bun agent-content-probe.ts

import { G2Session } from "g2-kit/ble";

const TAG = 7;
const TEXT = "hi";

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
  return [...tagByte(f, 0), ...varint(v)];
}
function wrapOuter(magic: number, tag: number, submsg: number[]): Uint8Array {
  return new Uint8Array([...tagByte(1, 0), ...varint(magic), ...tagByte(tag, 2), ...varint(submsg.length), ...submsg]);
}

// Candidate inner layouts for agent-content's submessage, guessing field order
// from the CLI's own arg order (style, op, text) and common conventions.
const CANDIDATES: Array<{ desc: string; submsg: number[] }> = [
  { desc: "{1:style=1(hi), 2:op=2(rep), 3:text}", submsg: [...varField(1, 1), ...varField(2, 2), ...strField(3, TEXT)] },
  { desc: "{1:text, 2:style=1, 3:op=2}", submsg: [...strField(1, TEXT), ...varField(2, 1), ...varField(3, 2)] },
  { desc: "{1:op=2(rep), 2:style=1(hi), 3:text}", submsg: [...varField(1, 2), ...varField(2, 1), ...strField(3, TEXT)] },
  { desc: "{1:text} only", submsg: [...strField(1, TEXT)] },
  { desc: "{3:text} only (matches decompiled offset+4=text start hint)", submsg: [...strField(3, TEXT)] },
];

console.log(`[agent-content] tag=${TAG}  ${CANDIDATES.length} candidate layouts`);
const session = await G2Session.open();
console.log(`[agent-content] connected.`);

session.onRawFrame((frame, arm) => {
  if (!frame.ok || frame.sid !== 0x30) return;
  console.log(`[${ts()}] ${arm} sid=0x30 flag=0x${frame.flag.toString(16)} pb=${Buffer.from(frame.pb).toString("hex")}  <-- TERMINAL`);
});

let magic = 60;
for (const c of CANDIDATES) {
  const pb = wrapOuter(magic, TAG, c.submsg);
  console.log(`\n[agent-content] >>> sending ${c.desc}  magic=${magic}  bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[agent-content] direct ack: pb=${Buffer.from(ack.pb).toString("hex")}` : `[agent-content] no direct ack, watching 2s...`);
  await new Promise((r) => setTimeout(r, 2000));
  magic++;
}

console.log("\n[agent-content] done. Watching 5s more for trailing traffic...");
await new Promise((r) => setTimeout(r, 5000));
await session.close();
process.exit(0);
