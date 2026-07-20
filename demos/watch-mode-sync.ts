#!/usr/bin/env bun
// Diagnostic: stay connected (don't disconnect), send mode_sync, then long pauses
// for a human to actually look at the physical lens at each step -- to disambiguate
// whether CommResp{errCode=1} really means "action rejected" or is a generic ack
// unrelated to the real per-action outcome (which might only be visible on-lens).
//
//   bun watch-mode-sync.ts
// Ctrl+C to stop (BLE central will just drop when the process dies).

import { G2Session } from "g2-kit/ble";

function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }
function varint(n: number): number[] {
  const out: number[] = [];
  let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function wrapOuter(magic: number, tag: number, submsg: number[]): Uint8Array {
  return new Uint8Array([...tagByte(1, 0), ...varint(magic), ...tagByte(tag, 2), ...varint(submsg.length), ...submsg]);
}

const session = await G2Session.open();
console.log(`[watch] connected. STAYING CONNECTED -- look at the lens now (before any send).`);

session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  const hex = Buffer.from(frame.pb).toString("hex");
  const tagStr = frame.sid === 0x30 ? "  <-- TERMINAL" : "";
  console.log(`[${ts()}] ${arm} sid=0x${frame.sid.toString(16)} flag=0x${frame.flag.toString(16)} pb=${hex}${tagStr}`);
});

let magic = 400;
console.log("\n[watch] waiting 8s -- baseline, check lens now...");
await new Promise((r) => setTimeout(r, 8000));

{
  const sub = [...tagByte(1, 0), ...varint(2)];
  const pb = wrapOuter(magic, 3, sub);
  console.log(`\n[watch] >>> SENDING mode_sync(value=2)  magic=${magic}  bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[watch] ack: ${Buffer.from(ack.pb).toString("hex")}` : "[watch] no direct ack");
  magic++;
}
console.log("\n[watch] waiting 10s -- CHECK LENS NOW, did anything change?");
await new Promise((r) => setTimeout(r, 10000));

console.log("\n[watch] staying connected another 20s in case of delayed effects, then will exit (BLE stays up the whole time)...");
await new Promise((r) => setTimeout(r, 20000));
console.log("[watch] done, disconnecting now.");
await session.close();
process.exit(0);
