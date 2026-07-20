#!/usr/bin/env bun
// v2: respects the newly-discovered magic sequencing requirement (must be exactly
// last_accepted+1, persists across BLE disconnects -- NOT just "any distinct value
// outside the 3s dedup window" as previously assumed). Pass the starting magic
// explicitly since we have to track it by hand across script invocations now.
import { G2Session } from "g2-kit/ble";
function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }
function varint(n: number): number[] {
  const out: number[] = []; let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function varField(f: number, v: number): number[] { if (v === 0) return []; return [...tagByte(f, 0), ...varint(v)]; }
function wrapOuter(magic: number, tag: number, submsg: number[]): Uint8Array {
  return new Uint8Array([...tagByte(1, 0), ...varint(magic), ...tagByte(tag, 2), ...varint(submsg.length), ...submsg]);
}
const START_MAGIC = Number(process.argv[2] ?? "3");
const SESSION_ID = Number(process.argv[3] ?? "1");
const session = await G2Session.open();
console.log(`[v2] connected. starting magic=${START_MAGIC}, session_id=${SESSION_ID}`);
session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  console.log(`[${ts()}] ${arm} sid=0x${frame.sid.toString(16)} pb=${Buffer.from(frame.pb).toString("hex")}`);
});
let magic = START_MAGIC;
console.log("[v2] waiting 5s baseline, check lens...");
await new Promise(r => setTimeout(r, 5000));
{
  const sub = [...varField(1, SESSION_ID)];
  const pb = wrapOuter(magic, 21, sub);
  console.log(`\n[v2] >>> session_id_changed(id=${SESSION_ID}) magic=${magic} bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[v2] ack: ${Buffer.from(ack.pb).toString("hex")}` : "[v2] no direct ack");
  magic++;
}
console.log("[v2] waiting 8s, check lens...");
await new Promise(r => setTimeout(r, 8000));
console.log(`[v2] next magic would be ${magic}`);
await new Promise(r => setTimeout(r, 10000));
await session.close();
process.exit(0);
