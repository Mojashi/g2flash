#!/usr/bin/env bun
// Terminal mode is already confirmed persistently active (lens shows CLOSED state's
// "Start by connecting to a Host in the app" prompt). Skip re-sending mode_sync --
// go straight for the escape hatch found by the FSM reconstruction: event 35
// (SESSION_ID_CHANGED), RX discriminant=10, wire tag=21, single u32 field.
// Stay connected with long pauses so a human can watch the physical lens.
//
//   bun watch-session-id-changed.ts [id]

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

const session = await G2Session.open();
console.log(`[watch-sid] connected. session_id=${SESSION_ID}. Look at the lens now (baseline).`);

session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  const hex = Buffer.from(frame.pb).toString("hex");
  const tagStr = frame.sid === 0x30 ? "  <-- TERMINAL" : "";
  console.log(`[${ts()}] ${arm} sid=0x${frame.sid.toString(16)} flag=0x${frame.flag.toString(16)} pb=${hex}${tagStr}`);
});

let magic = 500;
console.log("\n[watch-sid] waiting 6s -- baseline, check lens now...");
await new Promise((r) => setTimeout(r, 6000));

{
  const sub = [...varField(1, SESSION_ID)];
  const pb = wrapOuter(magic, 21, sub);
  console.log(`\n[watch-sid] >>> SENDING session_id_changed(id=${SESSION_ID})  magic=${magic}  bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[watch-sid] ack: ${Buffer.from(ack.pb).toString("hex")}` : "[watch-sid] no direct ack");
  magic++;
}
console.log("\n[watch-sid] waiting 12s -- CHECK LENS NOW, did the 'connect to Host' prompt change?");
await new Promise((r) => setTimeout(r, 12000));

console.log("\n[watch-sid] staying connected another 15s for any delayed effect, then exiting...");
await new Promise((r) => setTimeout(r, 15000));
console.log("[watch-sid] done, disconnecting now.");
await session.close();
process.exit(0);
