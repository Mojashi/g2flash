#!/usr/bin/env bun
// imu-scan.ts — load payload, open, then send 'I' repeatedly. The payload reads 32 u32 from the
// headup filter ctx twice (100ms apart) and reports which offsets CHANGED (= live sensor fields).
// We also scan the ring buffer base the same way. Run for a few seconds while tilting your head.
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 3 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });

console.log("reset+load+open...");
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);
await w(send([0x67])); await Bun.sleep(1000);

console.log("scanning headup filter ctx for live fields (tilt your head)...\n");
const allChanged = new Map<number, number[]>();
for (let t = 0; t < 10; t++) {
  latest = null;
  await w(send([0x49])); // 'I'
  await Bun.sleep(300);
  if (!latest || latest.length < 3) { console.log(`  scan ${t}: no reply`); continue; }
  const cnt = latest[2]!;
  const fields: string[] = [];
  for (let i = 0; i < cnt; i++) {
    const off = latest[3 + i * 5]!;
    const val = u32at(latest, 3 + i * 5 + 1);
    const fv = f32(val);
    fields.push(`+0x${off.toString(16).padStart(2, "0")}=${fv.toFixed(3)}`);
    if (!allChanged.has(off)) allChanged.set(off, []);
    allChanged.get(off)!.push(fv);
  }
  console.log(`  scan ${t}: ${cnt} changed: ${fields.join("  ")}`);
}

console.log("\n=== SUMMARY: offsets that changed at least once ===");
for (const [off, vals] of [...allChanged.entries()].sort((a, b) => a[0] - b[0])) {
  const min = Math.min(...vals), max = Math.max(...vals);
  console.log(`  +0x${off.toString(16).padStart(2, "0")}: seen ${vals.length}x, range [${min.toFixed(3)} .. ${max.toFixed(3)}], span=${(max - min).toFixed(3)}`);
}
await s.close(); process.exit(0);
