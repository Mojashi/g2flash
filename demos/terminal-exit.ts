#!/usr/bin/env bun
// Switch the glasses back to the DEFAULT (daily/dashboard) mode by leaving terminal
// mode. mode_sync (discriminant 1) with cmd != 2 => "leave terminal mode / go daily".
// Confirmed: the glasses reply with StatusReply current_mode=1 (default).
//
//   bun terminal-exit.ts
import { G2Session } from "g2-kit/ble";

function varint(n: number): number[] { const o: number[] = []; let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; o.push(b); } while (v); return o; }
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function vfield(f: number, v: number): number[] { return [...tagByte(f, 0), ...varint(v)]; }
function bfield(f: number, d: number[]): number[] { return [...tagByte(f, 2), ...varint(d.length), ...d]; }
// mode_sync: field1=disc(1), field2=magic, oneof tag3 {f1=cmd}
function modeSync(cmd: number, magic: number): Uint8Array {
  return new Uint8Array([...vfield(1, 1), ...vfield(2, magic), ...bfield(3, vfield(1, cmd))]);
}

const magic = Number(process.argv[2] ?? "1");
const session = await G2Session.open();
console.log("connected -- sending mode_sync(cmd=0) -> leave terminal, back to default/daily");
session.onRawFrame((f) => {
  if (f.ok && f.sid === 0x30) console.log("  <-- sid=0x30 pb=" + Buffer.from(f.pb).toString("hex"));
});
const ack = await session.sendPb(0x30, modeSync(0, magic), magic, { ackTimeoutMs: 2500 });
console.log(ack ? "ack: " + Buffer.from(ack.pb).toString("hex") + "  (back to default mode)" : "no direct ack");
await new Promise((r) => setTimeout(r, 2500));
await session.close();
process.exit(0);
