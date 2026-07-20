#!/usr/bin/env bun
// r-clean.ts — isolate the R lens: reset+load+activate R ONLY, ping, open, poll 'k'. Logs the ARM
// TAG of every reply so we can see routing. No L traffic, no double-anything.
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FRAG = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const hex = (b: Uint8Array) => Buffer.from(b).toString("hex");
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (arm: "L" | "R", pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm }); ack.catch(() => null); };
s.onRawFrame((f: any, _raw: Uint8Array, arm: "L" | "R") => { if (!f.ok || f.sid !== SID) return; const p = f.pb; if (p.length < 1 || p[0] !== 0xa7) return; console.log(`    <- [arm ${arm}] ${hex(p)}`); });
console.log(`payload ${blob.length}B crc=0x${crc.toString(16)}`);
console.log("reset R, load R..."); await w("R", Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FRAG); for (let i = 0; i < n; i++) { await w("R", frag(i, i === n - 1, blob.subarray(i * FRAG, Math.min((i + 1) * FRAG, blob.length)))); await Bun.sleep(14); }
console.log("activate R:"); await w("R", act(blob.length, crc)); await Bun.sleep(600);
console.log("ping R:"); await w("R", Uint8Array.from([5])); await Bun.sleep(600);
console.log("open mode R ('g'):"); await w("R", send([0x67])); await Bun.sleep(1500);
console.log("poll 'k' R 6x:");
for (let i = 0; i < 6; i++) { await w("R", send([0x6b])); await Bun.sleep(500); }
await s.close(); process.exit(0);
