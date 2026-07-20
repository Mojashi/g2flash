#!/usr/bin/env bun
// Try session_status_update (wire tag=6, RX discriminant=4) to move IDLE(2) -> AGENT_PROCESSING(7).
// Handler requires session_id (some field in this submsg) to match current_session
// (non-zero) or it silently self-loops. We just set current_session=1 via
// session_id_changed(id=1), so try session_id=1 here too.
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
const START_MAGIC = Number(process.argv[2] ?? "4");
const SESSION_ID = Number(process.argv[3] ?? "1");
const session = await G2Session.open();
console.log(`[status] connected. magic=${START_MAGIC} session_id=${SESSION_ID}`);
session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  console.log(`[${ts()}] ${arm} sid=0x${frame.sid.toString(16)} pb=${Buffer.from(frame.pb).toString("hex")}`);
});
let magic = START_MAGIC;
console.log("[status] waiting 5s baseline, check lens...");
await new Promise(r => setTimeout(r, 5000));
{
  // try f1=1 (status?), f2=session_id
  const sub = [...varField(1, 1), ...varField(2, SESSION_ID)];
  const pb = wrapOuter(magic, 6, sub);
  console.log(`\n[status] >>> session_status_update(f1=1,session=${SESSION_ID}) magic=${magic} bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[status] ack: ${Buffer.from(ack.pb).toString("hex")}` : "[status] no direct ack");
  magic++;
}
console.log("[status] waiting 8s, CHECK LENS -- did it change from 'Waiting Input'?");
await new Promise(r => setTimeout(r, 8000));
console.log(`[status] next magic would be ${magic}`);
await new Promise(r => setTimeout(r, 8000));
await session.close();
process.exit(0);
