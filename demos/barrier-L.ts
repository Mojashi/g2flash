#!/usr/bin/env bun
// barrier-L.ts — arm-L ONLY (reaches BOTH lenses: L runs locally + relays to R). Never touches arm R,
// so R is loaded exactly ONCE (no double-load crash). Loads+opens both, measures the R vs L frame
// delta in BASELINE (no sync) then with the wait-for-ack BARRIER ('m'). Reads:
//   'k' -> the R(side1) instance replies R's frame ; the L(side2) instance is reply-gated (silent)
//   'l' -> the L instance relays its frame over the peer to R, R replies it. So 'k'=R, 'l'=L.
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225, ARM = "L" as const;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32 = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: ARM }); ack.catch(() => null); };
let R: number | null = null, L: number | null = null, act1: number | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb; if (p.length < 2 || p[0] !== 0xa7) return;
  if (p[1] === 0x02) act1 = p[2]; else if (p[1] === 0x6b && p.length >= 6) R = u32(p, 2); else if (p[1] === 0x6c && p.length >= 6) L = u32(p, 2); });
async function pair(): Promise<string> { R = null; L = null;
  await w(send([0x6b])); await w(send([0x6c])); await Bun.sleep(500);
  const d = R != null && L != null ? R - L : null; return `R=${R ?? "-"}  L=${L ?? "-"}  delta(R-L)=${d ?? "?"}`; }

console.log(`payload ${blob.length}B; ALL via arm ${ARM}. reset...`);
await w(Uint8Array.from([4])); await Bun.sleep(400);
const n = Math.ceil(blob.length / FR); for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400); console.log(`  activate reply active=${act1}`);
console.log("open both ('g')..."); await w(send([0x67])); await Bun.sleep(1500);
console.log("\n=== BASELINE (no barrier) — expect delta nonzero/drifting ===");
for (let i = 0; i < 4; i++) console.log("  " + await pair());
console.log("\n=== enable BARRIER: 'm' (both lenses; R=master by side) ===");
await w(send([0x6d])); await Bun.sleep(1800);
console.log("=== WITH BARRIER — expect delta small + stable ===");
for (let i = 0; i < 8; i++) console.log("  " + await pair());
console.log("\n(restore) 'n'"); await w(send([0x6e]));
await s.close(); process.exit(0);
