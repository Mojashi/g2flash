#!/usr/bin/env bun
// axis-shot.ts — Load payload, open, enable IMU, wait, take screenshot
import { G2Session } from "g2-kit/ble";
import { readFileSync, writeFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };

// Collect QOI screenshot fragments
const qoiFrags: Uint8Array[] = [];
let shotDone = false;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== 0x7d) return;
  const p = f.pb;
  if (p.length >= 8) {
    qoiFrags.push(new Uint8Array(p));
    // QOI end marker: 0x00 0x00 0x00 0x00 0x00 0x00 0x00 0x01
    if (p.length >= 8 && p[p.length-1]===1 && p[p.length-2]===0 && p[p.length-3]===0 && p[p.length-4]===0 &&
        p[p.length-5]===0 && p[p.length-6]===0 && p[p.length-7]===0 && p[p.length-8]===0) shotDone = true;
  }
});

console.log(`Loading ${blob.length}B...`);
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);

console.log("Open + barrier + stereo + IMU...");
await w(send([0x67])); await Bun.sleep(1500);
await w(send([0x6d])); await Bun.sleep(300);
await w(send([0x64])); await Bun.sleep(300);
await w(send([0x69])); await Bun.sleep(2000);

console.log("Taking screenshot ('s')...");
await w(send([0x73])); // 's' = capture

// Wait for QOI fragments to arrive
for (let i = 0; i < 50 && !shotDone; i++) await Bun.sleep(200);

if (qoiFrags.length > 0) {
  // Concatenate all fragments (strip framing if needed)
  const total = qoiFrags.reduce((s, f) => s + f.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const f of qoiFrags) { out.set(f, off); off += f.length; }
  const outPath = new URL("../axis-screenshot.qoi", import.meta.url).pathname;
  writeFileSync(outPath, out);
  console.log(`✓ Screenshot saved: ${outPath} (${qoiFrags.length} frags, ${total} bytes)`);
} else {
  console.log("✗ No screenshot received");
}

await s.close(); process.exit(0);
