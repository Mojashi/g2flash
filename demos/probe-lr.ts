#!/usr/bin/env bun
// probe-lr.ts — READ-ONLY: poll each lens's frame counter to detect which lens is animating.
//   'k' (0x6b) -> R replies its frame [0xA7 6b f0..f3 side]
//   'l' (0x6c) -> L reports its frame over the peer link; R relays it [0xA7 6c f0..f3 side]
// No load, no mode changes. If R advances and L is (no reply)/stuck, only R is running.
import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => { const f = new Uint8Array(2 + d.length); f[0] = 3; f[1] = MODE; f.set(d, 2); return f; };
const u32 = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;
const session = await G2Session.open({ quiet: true });
let seq = 1;
const write = async (arm: "L" | "R", pb: Uint8Array) => { const { ack } = await session.sendPbPipelined(SID, pb, seq++ & 0xff, { arm }); ack.catch(() => null); };
let R: number | null = null, L: number | null = null, Rs: number | null = null, Ls: number | null = null;
session.onRawFrame((f: any) => {
  if (!f.ok || f.sid !== SID) return; const p = f.pb; if (p.length < 2 || p[0] !== 0xa7) return;
  if (p[1] === 0x6b && p.length >= 7) { R = u32(p, 2); Rs = p[6]; }
  else if (p[1] === 0x6c && p.length >= 7) { L = u32(p, 2); Ls = p[6]; }
});
console.log("polling R('k') and L('l') frame counters 8x (read-only)...");
for (let i = 0; i < 8; i++) {
  R = null; L = null;
  await write("R", send([0x6b])); await write("L", send([0x6c])); await Bun.sleep(500);
  console.log(`  t=${i}s  R=${R ?? "(no reply)"}${Rs != null ? " side" + Rs : ""}   L=${L ?? "(no reply)"}${Ls != null ? " side" + Ls : ""}`);
}
await session.close(); process.exit(0);
