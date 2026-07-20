#!/usr/bin/env bun
// imu-snap.ts — load, open, then call 'I' multiple times from the HOST side with real delays between
// (no busywait on-device, so the RTOS actually runs other tasks between our reads). Diff consecutive
// snapshots to find which SRAM words are alive. Tilt your head between snapshots.
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
  if (p.length >= 258 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });

console.log("reset+load+open...");
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);
await w(send([0x67])); await Bun.sleep(1000);

const NAMES = ["fctx", "ring"];
const snaps: Uint32Array[] = [];
console.log("taking 6 snapshots (1s apart, TILT YOUR HEAD between them)...\n");
for (let t = 0; t < 6; t++) {
  latest = null;
  await w(send([0x49]));
  await Bun.sleep(1000);
  if (!latest || latest.length < 114) { console.log(`  snap ${t}: no reply (len=${latest?.length ?? 0})`); snaps.push(new Uint32Array(28)); continue; }
  const vals = new Uint32Array(28);
  for (let j = 0; j < 28; j++) vals[j] = u32at(latest, 2 + j * 4);
  snaps.push(vals);
  console.log(`  snap ${t} OK`);
}

console.log("\n=== DIFF: words that changed between consecutive snapshots ===");
const everChanged = new Set<number>();
for (let t = 1; t < snaps.length; t++) {
  const diffs: string[] = [];
  for (let j = 0; j < 28; j++) {
    if (snaps[t]![j] !== snaps[t - 1]![j]) {
      const reg = 0;
      const off = j * 4;
      diffs.push(`${NAMES[reg]}+0x${off.toString(16).padStart(2, "0")}=${f32(snaps[t]![j]!).toFixed(4)}(was ${f32(snaps[t - 1]![j]!).toFixed(4)})`);
      everChanged.add(j);
    }
  }
  console.log(`  ${t - 1}->${t}: ${diffs.length} changed: ${diffs.join("  ") || "(none)"}`);
}
console.log(`\n${everChanged.size} unique SRAM words changed at least once (these are the live sensor fields).`);
await s.close(); process.exit(0);
