#!/usr/bin/env bun
// Combined send+listen: try candidate "host status" messages (the presumed next
// phase after mode_sync -- see docs/terminal-protocol.md and the debug CLI's
// `terminal host <0-2>` : 0=no_host 1=offline 2=streaming) on each remaining
// untagged oneof tag, and watch ALL subsequent traffic (not just the direct ack)
// for a few seconds after each send -- some messages may not ack directly but
// still trigger an async DisplayStateNotify we can observe.
//
//   bun terminal-probe2.ts                      # try all remaining candidates, value=2
//   bun terminal-probe2.ts 5,6,7 1               # try specific tags with value=1
//
// Single BLE session for both send + listen -- run this INSTEAD OF a separate
// terminal-sniff.ts (they'd fight over the connection).

import { G2Session } from "g2-kit/ble";

const REMAINING_TAGS = [4, 5, 6, 7, 8, 14, 15, 16, 17, 21, 23];
const tags = process.argv[2] ? process.argv[2].split(",").map(Number) : REMAINING_TAGS;
const VALUE = process.argv[3] === "empty" ? null : process.argv[3] ? Number(process.argv[3]) : 2;
const WATCH_MS = Number(process.env.G2_WATCH_MS ?? "3000");

function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }
function varint(n: number): number[] {
  const out: number[] = [];
  let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function build(magic: number, tag: number, value: number | null): Uint8Array {
  const sub = value === null ? [] : [...tagByte(1, 0), ...varint(value)];
  return new Uint8Array([...tagByte(1, 0), ...varint(magic), ...tagByte(tag, 2), ...varint(sub.length), ...sub]);
}

console.log(`[probe2] candidates: ${tags.join(", ")}  value=${VALUE}  watch=${WATCH_MS}ms`);
const session = await G2Session.open();
console.log(`[probe2] connected.`);

session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  const hex = Buffer.from(frame.pb).toString("hex");
  const tagStr = frame.sid === 0x30 ? "  <-- TERMINAL" : "";
  console.log(`[${ts()}] ${arm} sid=0x${frame.sid.toString(16)} flag=0x${frame.flag.toString(16)} pb=${hex}${tagStr}`);
});

let magic = 30; // start well clear of earlier tests, monotonic, never reused
for (const tag of tags) {
  const pb = build(magic, tag, VALUE);
  console.log(`\n[probe2] >>> sending tag=${tag} value=${VALUE} magic=${magic}  bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[probe2] direct ack: pb=${Buffer.from(ack.pb).toString("hex")}` : `[probe2] no direct ack -- watching ${WATCH_MS}ms for async traffic...`);
  await new Promise((r) => setTimeout(r, WATCH_MS));
  magic++;
}

console.log("\n[probe2] done with all candidates. Staying connected 5s more to catch trailing traffic...");
await new Promise((r) => setTimeout(r, 5000));
await session.close();
process.exit(0);
