#!/usr/bin/env bun
// imu-scan3.ts — scan BEFORE opening our foreground mode ('g'). If the filter ctx updates here
// but not after 'g', it proves our foreground mode kills the IMU update.
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
  if (p.length >= 4 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });
const NAMES = ["filter_ctx", "ring_buf"];
function parseReply(p: Uint8Array): string {
  if (!p || p.length < 4) return "(no data)";
  const cntA = p[2]!, cntB = p[3]!; let pos = 4; const e: string[] = [];
  for (let i = 0; i < cntA + cntB && pos + 6 <= p.length; i++) {
    const reg = p[pos]!, off = p[pos + 1]!, val = u32at(p, pos + 2); pos += 6;
    e.push(`${NAMES[reg]}+0x${off.toString(16).padStart(2, "0")}=${f32(val).toFixed(4)}`);
  }
  return `${cntA}+${cntB} changed: ${e.join("  ") || "(none)"}`;
}

console.log("reset+load (NO 'g' yet — dashboard still foreground)...");
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(600);

console.log("\n=== BEFORE 'g' (dashboard foreground, IMU should be active) ===");
for (let t = 0; t < 4; t++) { latest = null; await w(send([0x49])); await Bun.sleep(1200); console.log(`  scan ${t}: ${parseReply(latest!)}`); }

console.log("\n=== opening our mode ('g') ===");
await w(send([0x67])); await Bun.sleep(1500);

console.log("\n=== AFTER 'g' (our foreground mode — does IMU still update?) ===");
for (let t = 0; t < 4; t++) { latest = null; await w(send([0x49])); await Bun.sleep(1200); console.log(`  scan ${t}: ${parseReply(latest!)}`); }
await s.close(); process.exit(0);
