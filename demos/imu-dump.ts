#!/usr/bin/env bun
// imu-dump.ts — load and dump the first 64 bytes of the IMU ring buffer + 16 bytes of the headup
// filter ctx delay line, twice with a 500ms gap, to see what values are live and which change.
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const hex = (b: Uint8Array) => Buffer.from(b).toString("hex");
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 90 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });

console.log("reset+load+open...");
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);
await w(send([0x67])); await Bun.sleep(1000);

function printDump(label: string, p: Uint8Array) {
  const ringAddr = u32at(p, 2);
  console.log(`\n${label}: ring @0x${ringAddr.toString(16)}`);
  // print 64 bytes as hex + u32/i16/float annotations
  for (let row = 0; row < 64; row += 16) {
    const h = hex(p.subarray(6 + row, 6 + row + 16));
    const u = [0, 4, 8, 12].map(o => u32at(p, 6 + row + o).toString(16).padStart(8, "0")).join(" ");
    console.log(`  +0x${row.toString(16).padStart(2, "0")}: ${h}  u32: ${u}`);
  }
  // annotate a few positions as int16/float
  for (const off of [0x0c, 0x10, 0x12, 0x14, 0x16, 0x18, 0x1c, 0x20, 0x24, 0x28, 0x2c, 0x30, 0x34, 0x38]) {
    if (off + 4 > 64) break;
    const fv = f32(u32at(p, 6 + off));
    const iv = (p[6 + off]! | (p[7 + off]! << 8)); const si = iv > 32767 ? iv - 65536 : iv;
    console.log(`    +0x${off.toString(16).padStart(2, "0")} float=${fv.toFixed(6)} i16=${si} u16=${iv}`);
  }
  // headup filter ctx
  const fctxAddr = u32at(p, 70);
  console.log(`  filter ctx @0x${fctxAddr.toString(16)} delay+output (+0x28..+0x3c):`);
  for (let j = 0; j < 4; j++) {
    const fv = f32(u32at(p, 74 + j * 4));
    console.log(`    +0x${(0x28 + j * 4).toString(16)}: float=${fv.toFixed(6)}`);
  }
}

for (let t = 0; t < 3; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(500);
  if (latest) printDump(`sample ${t}`, latest); else console.log(`sample ${t}: no reply`);
}
await s.close(); process.exit(0);
