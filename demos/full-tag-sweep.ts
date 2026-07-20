#!/usr/bin/env bun
// Brute-force sweep: send an EMPTY submessage for every wire tag 3-25 and watch
// for anything other than the generic CommResp{errCode=1} rejection. tag=3
// (mode_sync) is known-valid and empty-safe (no side effect expected here since
// value=0/default won't trigger the ==2 special case). Purpose: empirically
// find which tags the firmware treats differently, without relying on the
// (possibly wrong) "wire_tag = discriminant_byte + 2" hypothesis.
import { G2Session } from "g2-kit/ble";

function varint(n: number): number[] {
  const out: number[] = []; let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function build(magic: number, tag: number): Uint8Array {
  return new Uint8Array([...tagByte(1, 0), ...varint(magic), ...tagByte(tag, 2), ...varint(0)]);
}

const session = await G2Session.open();
console.log("connected");
session.onRawFrame((frame) => {
  if (!frame.ok || frame.sid !== 0x30) return;
  console.log(`  <-- TERMINAL RESP: ${Buffer.from(frame.pb).toString("hex")}`);
});
let magic = 80;
for (let tag = 3; tag <= 25; tag++) {
  const pb = build(magic, tag);
  console.log(`sending tag=${tag} magic=${magic}`);
  await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1200 }).catch(() => null);
  await new Promise((r) => setTimeout(r, 3500)); // > 3s dedup window, avoid contaminating results
  magic++;
}
console.log("done, draining 3s");
await new Promise((r) => setTimeout(r, 3000));
await session.close();
process.exit(0);
