#!/usr/bin/env bun
// stereo-imu.ts — Full stereo 3D demo with gyro head-tracking. The complete experience.
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };

let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 26 && p[0] === 0xa7 && p[1] === 0x49) latest = new Uint8Array(p);
});

console.log(`Loading ${blob.length}B...`);
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);

console.log("1. Open mode ('g')...");
await w(send([0x67])); await Bun.sleep(1500);

console.log("2. Barrier ON ('m')...");
await w(send([0x6d])); await Bun.sleep(500);

console.log("3. Stereo ON ('d')...");
await w(send([0x64])); await Bun.sleep(500);

console.log("4. IMU head-tracking ON ('i')...");
await w(send([0x69])); await Bun.sleep(1000);

console.log("\n✓ STEREO + IMU ACTIVE — LOOK AROUND!");
console.log("  The 3D icosahedron should rotate as you turn your head.");
console.log("  Monitoring gyro for 30s...\n");

for (let t = 0; t < 60; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(500);
  if (!latest) continue;
  const grx = i16at(latest, 8), gry = i16at(latest, 22), grz = i16at(latest, 24);
  const gcx = i16at(latest, 16)/100, gcy = i16at(latest, 18)/100, gcz = i16at(latest, 20)/100;
  const imuOn = latest[2];
  const angY = latest[3], angX = latest[4];
  console.log(`  [${(t*0.5).toFixed(0).padStart(2)}s] imu=${imuOn} ang=[Y:${angY.toString().padStart(3)},X:${angX.toString().padStart(3)}] raw=[${grx.toString().padStart(5)},${gry.toString().padStart(5)},${grz.toString().padStart(5)}] cal=[${gcx.toFixed(1).padStart(5)},${gcy.toFixed(1).padStart(5)},${gcz.toFixed(1).padStart(5)}]`);
}

console.log("\n(leaving active — 'q' via arm-L to close)");
await s.close(); process.exit(0);
