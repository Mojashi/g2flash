#!/usr/bin/env bun
// full-test.ts — clean load + open + barrier + stereo + IMU head-tracking, all in one session.
// arm-L only. After enabling IMU, holds 15s for you to move your head and watch the model track.
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32 = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let R: number | null = null, L: number | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb; if (p.length < 2 || p[0] !== 0xa7) return;
  if (p[1] === 0x6b && p.length >= 6) R = u32(p, 2); else if (p[1] === 0x6c && p.length >= 6) L = u32(p, 2); });
async function pair() { R = null; L = null; await w(send([0x6b])); await w(send([0x6c])); await Bun.sleep(500); const d = R != null && L != null ? R - L : null; return `R=${R ?? "-"} L=${L ?? "-"} d=${d ?? "?"}`; }

console.log(`payload ${blob.length}B crc=0x${crc.toString(16)}; arm-L clean load...`);
await w(Uint8Array.from([4])); await Bun.sleep(400);
const n = Math.ceil(blob.length / FR); for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);
console.log("'g' open..."); await w(send([0x67])); await Bun.sleep(1500);
console.log("'m' barrier ON..."); await w(send([0x6d])); await Bun.sleep(1000);
console.log("sync check:"); for (let i = 0; i < 3; i++) console.log("  " + await pair());
console.log("'d' stereo ON..."); await w(send([0x64])); await Bun.sleep(500);
console.log("sync + stereo check:"); for (let i = 0; i < 3; i++) console.log("  " + await pair());
console.log("\n'i' IMU HEAD-TRACKING ON — move your head! Holding 15s...");
await w(send([0x69]));
for (let i = 0; i < 10; i++) { console.log("  " + await pair()); await Bun.sleep(1000); }
console.log("'i' IMU off, 'n' barrier off..."); await w(send([0x69])); await w(send([0x6e]));
await s.close(); process.exit(0);
