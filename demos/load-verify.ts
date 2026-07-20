#!/usr/bin/env bun
// load-verify.ts — fresh-load the payload to BOTH lenses, open the mode on both, then poll each
// lens's frame counter to check BOTH actually animate (the L-runs question). Scoped: no sync phase.
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
let R: number | null = null, L: number | null = null; const marks: string[] = [];
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb; if (p.length < 2 || p[0] !== 0xa7) return;
  if (p[1] === 0x6b && p.length >= 6) R = u32(p, 2);
  else if (p[1] === 0x6c && p.length >= 6) L = u32(p, 2);
  else marks.push(`0x${p[1].toString(16)}:${Array.from(p.subarray(2, 6)).join(",")}`); });
async function upload(arm: "L" | "R") { const n = Math.ceil(blob.length / FRAG); for (let i = 0; i < n; i++) { await w(arm, frag(i, i === n - 1, blob.subarray(i * FRAG, Math.min((i + 1) * FRAG, blob.length)))); await Bun.sleep(14); } await w(arm, act(blob.length, crc)); await Bun.sleep(300); }
console.log(`payload ${blob.length}B crc=0x${crc.toString(16)}`);
console.log("RESET both, load R, load L..."); await w("R", Uint8Array.from([4])); await w("L", Uint8Array.from([4])); await Bun.sleep(300);
await upload("R"); await upload("L");
console.log(`markers after load: ${marks.slice(-6).join(" | ") || "(none)"}`);
console.log("open mode on R and L ('g')..."); await w("R", send([0x67])); await w("L", send([0x67])); await Bun.sleep(1500);
console.log("polling both counters (fresh window, before idle):");
let R0: number | null = null, L0: number | null = null, R9: number | null = null, L9: number | null = null;
for (let i = 0; i < 10; i++) { R = null; L = null; await w("R", send([0x6b])); await w("L", send([0x6c])); await Bun.sleep(450);
  if (R != null && R0 == null) R0 = R; if (L != null && L0 == null) L0 = L; if (R != null) R9 = R; if (L != null) L9 = L;
  console.log(`  t=${i}  R=${R ?? "-"}  L=${L ?? "-"}`); }
console.log(`\nR advanced: ${R0 != null && R9 != null ? R9 - R0 : "n/a"}   L advanced: ${L0 != null && L9 != null ? L9 - L0 : (L0 == null ? "NO REPLY (L not running / relay dead)" : "n/a")}`);
await s.close(); process.exit(0);
