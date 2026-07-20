#!/usr/bin/env bun
// sync-live.ts — NO reload. Both lenses already running. Discriminate architecture + test barrier:
//   'k'->R frame (side in byte6), 'l'->L asks its instance to relay its frame via peer->R.
//   If 'l' returns a frame DIFFERENT from 'k' => an independent L instance exists (barrier can work).
//   Then 'm'->R enables the wait-for-ack barrier; watch if R,L converge.
import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32 = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (arm: "L" | "R", pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm }); ack.catch(() => null); };
let R: number | null = null, L: number | null = null, Lside: number | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb; if (p.length < 2 || p[0] !== 0xa7) return;
  if (p[1] === 0x6b && p.length >= 7) R = u32(p, 2);
  else if (p[1] === 0x6c && p.length >= 7) { L = u32(p, 2); Lside = p[6]; } });
async function pair(): Promise<string> { R = null; L = null;
  await w("R", send([0x6b])); await w("L", send([0x6c])); await w("R", send([0x6c])); await Bun.sleep(500);
  const d = R != null && L != null ? R - L : null;
  return `R=${R ?? "-"}  L=${L ?? "-"}${Lside != null ? "(relaySide" + Lside + ")" : ""}  delta=${d ?? "?"}`; }
console.log("=== BASELINE (no barrier) — does 'l' return a DIFFERENT frame than 'k'? ===");
for (let i = 0; i < 4; i++) console.log("  " + await pair());
console.log("\n=== enable barrier: 'm' -> R (and L) ===");
await w("R", send([0x6d])); await w("L", send([0x6d])); await Bun.sleep(2000);
console.log("=== WITH barrier — do R and L converge? ===");
for (let i = 0; i < 8; i++) console.log("  " + await pair());
console.log("\n(restore) 'n' -> both");
await w("R", send([0x6e])); await w("L", send([0x6e]));
await s.close(); process.exit(0);
