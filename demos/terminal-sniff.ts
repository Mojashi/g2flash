#!/usr/bin/env bun
// Passive listener: connect to the glasses and log EVERY raw frame (both arms),
// highlighting sid=0x30 (terminal) traffic specifically. Use this while driving
// the glasses through the OFFICIAL app / a real host connection (e.g. voice
// input, agent replies) to capture real wire bytes for the terminal protocol
// instead of guessing field shapes blind -- see docs/terminal-protocol.md.
//
//   bun terminal-sniff.ts                # log everything, run until Ctrl-C
//   bun terminal-sniff.ts 0x30            # only print frames on this sid (hex)
//   G2_ENTER_MODE=1 bun terminal-sniff.ts # send the confirmed mode_sync trigger
//                                         # (tag=3{1:2} on sid=0x30) right after
//                                         # connecting, then keep listening on
//                                         # the SAME session -- avoids the gap
//                                         # where reconnecting drops back out of
//                                         # terminal mode before you can react.
//
// Listening is passive; G2_ENTER_MODE=1 additionally sends ONE known-good
// message to re-enter terminal mode, safe to use alongside a real host only if
// nothing else is fighting for the same BLE connection slot.

import { G2Session } from "g2-kit/ble";

const onlySid = process.argv[2] ? parseInt(process.argv[2], 16) : null;
const enterMode = process.env.G2_ENTER_MODE === "1";

function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }

function varint(n: number): number[] {
  const out: number[] = [];
  let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(fieldNum: number, wireType: number): number[] {
  return varint((fieldNum << 3) | wireType);
}
// outer{ magic=1, tag3{ 1: 2 } } -- confirmed live to switch the HUD into terminal mode.
const MODE_SYNC_ENTER = new Uint8Array([
  ...tagByte(1, 0), ...varint(1),
  ...tagByte(3, 2), ...varint(2), ...tagByte(1, 0), ...varint(2),
]);

console.log(`[sniff] connecting...${onlySid !== null ? `  (filtering sid=0x${onlySid.toString(16)})` : ""}`);
const session = await G2Session.open();
console.log(`[sniff] connected. Listening on both arms. Ctrl-C to stop.`);
if (onlySid === null) {
  console.log(`[sniff] tip: pass a sid in hex (e.g. "0x30") to filter to just that channel.`);
}

if (enterMode) {
  console.log(`[sniff] G2_ENTER_MODE=1: sending mode_sync tag=3{1:2} to (re-)enter terminal mode...`);
  const ack = await session.sendPb(0x30, MODE_SYNC_ENTER, 1, { ackTimeoutMs: 2000 });
  console.log(ack ? `[sniff] mode_sync ack: ${Buffer.from(ack.pb).toString("hex")}` : `[sniff] mode_sync: no ack`);
}

session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  if (onlySid !== null && frame.sid !== onlySid) return;
  const pbHex = Buffer.from(frame.pb).toString("hex");
  const ascii = Buffer.from(frame.pb).toString("latin1").replace(/[^\x20-\x7e]/g, ".");
  const tag = frame.sid === 0x30 ? "  <-- TERMINAL" : "";
  console.log(
    `[${ts()}] ${arm} sid=0x${frame.sid.toString(16).padStart(2, "0")} flag=0x${frame.flag.toString(16)} ` +
    `frag=${frame.fragIdx}/${frame.totalFrags} seq=${frame.transportSeq} len=${frame.pb.length}${tag}`,
  );
  console.log(`           pb hex:   ${pbHex}`);
  console.log(`           pb ascii: "${ascii}"`);
});

process.on("SIGINT", async () => {
  console.log("\n[sniff] closing...");
  await session.close();
  process.exit(0);
});

// keep alive
await new Promise(() => {});
