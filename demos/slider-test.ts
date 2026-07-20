#!/usr/bin/env bun
// slider-test.ts — non-interactive smoke test for host-driven rotation ('F'/'A'). Sets several
// explicit angles, reads back R's frame ('k') to confirm next_frame() picked up the manual value
// through the barrier (no reboot expected), then releases back to auto-rotate ('A').
import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const setFrame = (a: number) => send([0x46, a & 0xff, (a >>> 8) & 0xff, (a >>> 16) & 0xff, (a >>> 24) & 0xff]);
const u32 = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let R: number | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb; if (p.length < 6 || p[0] !== 0xa7 || p[1] !== 0x6b) return; R = u32(p, 2); });
async function readR(): Promise<number | null> { R = null; await w(send([0x6b])); await Bun.sleep(400); return R; }

for (const target of [0, 64, 128, 192, 40]) {
  await w(setFrame(target));
  await Bun.sleep(300);
  const got = await readR();
  console.log(`  set F=${target}  ->  R frame reads back = ${got}  ${got === target ? "OK" : "(mismatch/lag)"}`);
}
console.log("releasing manual mode ('A')...");
await w(send([0x41]));
await Bun.sleep(1000);
const a = await readR(), b2 = await readR();
console.log(`  after 'A': R frame ${a} -> ${b2} (should be auto-advancing again)`);
await s.close(); process.exit(0);
