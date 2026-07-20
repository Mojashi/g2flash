#!/usr/bin/env bun
// diag-arm.ts — definitive arm-routing test after a power cycle. Load+open R (arm R), confirm R
// animates. Then send a bare LOAD_FRAG idx0 to arm L (a "poison pill": if it lands on R it FREES
// R's active code buffer -> R hardfaults on the next tick). Re-poll R: survives => arm L is a
// separate device (the real L); dies => arm-L traffic is reaching R.
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FRAG = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32 = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (arm: "L" | "R", pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm }); ack.catch(() => null); };
let R: number | null = null;
s.onRawFrame((f: any, _r: Uint8Array, arm: "L" | "R") => { if (!f.ok || f.sid !== SID) return; const p = f.pb; if (p.length < 6 || p[0] !== 0xa7) return; if (p[1] === 0x6b) R = u32(p, 2); });
async function pollR(n: number, label: string) { let first: number | null = null, last: number | null = null;
  for (let i = 0; i < n; i++) { R = null; await w("R", send([0x6b])); await Bun.sleep(450); if (R != null) { if (first == null) first = R; last = R; } console.log(`  ${label} t=${i} R=${R ?? "(no reply)"}`); }
  return { first, last }; }
console.log("reset R + load R + open R...");
await w("R", Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FRAG); for (let i = 0; i < n; i++) { await w("R", frag(i, i === n - 1, blob.subarray(i * FRAG, Math.min((i + 1) * FRAG, blob.length)))); await Bun.sleep(14); }
await w("R", act(blob.length, crc)); await Bun.sleep(400); await w("R", send([0x67])); await Bun.sleep(1200);
console.log("PHASE A — R alone (expect frames advancing):");
const a = await pollR(4, "A");
console.log("\n>>> POISON PILL: send LOAD_FRAG idx0 to arm L (frees R's buffer IF arm-L==R) <<<");
await w("L", frag(0, false, Uint8Array.from([0, 0, 0, 0]))); await Bun.sleep(600);
console.log("PHASE B — R after the arm-L load (does R survive?):");
const b = await pollR(5, "B");
const survived = b.last != null && a.last != null && b.last > a.last;
console.log(`\nVERDICT: R ${survived ? "SURVIVED -> arm L is a SEPARATE device (real L), safe to load L independently"
  : "DIED (no advance/no reply) -> arm-L traffic is reaching R; cannot address L independently"}`);
await s.close(); process.exit(0);
