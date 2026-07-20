#!/usr/bin/env bun
// imu-poll.ts — load the payload, then rapidly send 'I' (IMU probe) and print the raw accel + filter
// values at whatever rate BLE can sustain. The INTERNAL update rate shows as "how often the values
// change between consecutive polls" — if values change every poll at ~30Hz, the sensor runs >= 30Hz.
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const u16at = (p: Uint8Array, o: number) => p[o]! | (p[o + 1]! << 8);
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 22 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });

console.log("reset+load+open...");
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);
await w(send([0x67])); await Bun.sleep(1000); // open mode
await w(send([0x6d])); await Bun.sleep(500); // barrier on

console.log("polling 'I' rapidly for 6s (move your head to see axes change)...");
let prevAx = 0, prevAy = 0, prevAz = 0, changes = 0, polls = 0;
const t0 = performance.now();
for (let i = 0; i < 120; i++) { // ~50ms interval -> ~24Hz poll for 6s
  latest = null;
  await w(send([0x49]));
  await Bun.sleep(50);
  polls++;
  if (!latest) continue;
  const ax = i16at(latest, 2), ay = i16at(latest, 4), az = i16at(latest, 6);
  const idx = u16at(latest, 8);
  const filt = f32(u32at(latest, 10));
  if (ax !== prevAx || ay !== prevAy || az !== prevAz) changes++;
  if (i < 20 || i % 10 === 0) console.log(`  #${i}  accel x=${ax} y=${ay} z=${az}  idx=${idx}  filt=${filt.toFixed(4)}${(ax !== prevAx || ay !== prevAy || az !== prevAz) ? " *" : ""}`);
  prevAx = ax; prevAy = ay; prevAz = az;
}
const elapsed = (performance.now() - t0) / 1000;
console.log(`\n${polls} polls in ${elapsed.toFixed(1)}s; values changed ${changes} times -> internal update rate >= ${(changes / elapsed).toFixed(1)} Hz`);
await s.close(); process.exit(0);
