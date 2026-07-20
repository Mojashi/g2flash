#!/usr/bin/env bun
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
const START_MAGIC = Number(process.argv[2] ?? "6");
const SID = Number(process.argv[3] ?? "1");
const session = await G2Session.open();
console.log(`[combined] connected. magic starts at ${START_MAGIC}, session=${SID}`);
session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  console.log(`[${ts()}] ${arm} sid=0x${frame.sid.toString(16)} pb=${Buffer.from(frame.pb).toString("hex")}`);
});
let magic = START_MAGIC;
console.log("[combined] waiting 4s baseline, check lens...");
await new Promise(r => setTimeout(r, 4000));

async function send(tag: number, sub: number[], label: string) {
  const pb = wrapOuter(magic, tag, sub);
  console.log(`\n[combined] >>> ${label} magic=${magic} bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[combined] ack: ${Buffer.from(ack.pb).toString("hex")}` : "[combined] no direct ack");
  magic++;
}

await send(21, [...varField(1, SID)], `session_id_changed(id=${SID})`);
await new Promise(r => setTimeout(r, 2500));
await send(6, [...varField(1, 1), ...varField(2, SID)], `session_status_update(status=1,id=${SID})`);
console.log("\n[combined] waiting 12s -- CHECK LENS NOW for ANY change from 'Waiting Input'...");
await new Promise(r => setTimeout(r, 12000));
console.log(`[combined] next magic would be ${magic}`);
await new Promise(r => setTimeout(r, 6000));
await session.close();
process.exit(0);
