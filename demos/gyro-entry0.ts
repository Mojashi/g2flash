#!/usr/bin/env bun
// gyro-entry0.ts — Read IMU data from entry 0 (ring base) vs entry idx to find where FW writes data
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const hex = (b: Uint8Array, from = 0, to?: number) => Buffer.from(b.subarray(from, to)).toString("hex");
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };

// We need a custom probe that reads from entry 0. Let's use a different approach:
// Read raw SRAM directly by sending a memory-read command. But we don't have one.
// Instead, let's use the 'D' dump but it reads entry[idx]. We need entry[0].
// For now, let's use 'I' which now reads from entry[idx]. The previous working code read from ring+0x10.
//
// KEY INSIGHT: the working code used ring+0x10 (flags) and ring+0x34 (accel).
// These are entry[0]+0x10 and entry[0]+0x34 IF the header is 0 bytes.
// OR these are header fields + entry overlap.
// Let's verify by reading the ring pointer and checking entries 0 through 5.

// Actually, the 'D' command reads entry[idx]. We need to also read entry[0].
// Let's write a quick hack: use memory read via the firmware. But we don't have a generic memread.
//
// Better approach: let's just check if the ORIGINAL offsets (ring+0x10, ring+0x34) still have valid data
// even after enabling gyro. The 'I' probe was changed to read from entry[idx], which is wrong.
// Let me create a new 'W' probe that reads from the OLD offsets (ring base).

// For now, use 'I' + 'D' as-is, BUT note that they read from entry[idx].
// What we can do: wait and see if idx changes (if data is being written, idx should increment).

const replies: { tag: string; data: Uint8Array }[] = [];
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p[0] === 0xa7) replies.push({ tag: String.fromCharCode(p[1]!), data: new Uint8Array(p) });
});

console.log(`Loading ${blob.length}B...`);
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);
console.log("Opening...");
await w(send([0x67])); await Bun.sleep(1500);

// Read ring pointer + index + test entry 0 vs entry idx
// We'll use the 'D' command (dumps entry[idx]) to check what entry idx looks like
// AND manually construct a memory read of entry[0]

// But first, let's just check: does the firmware ring index advance?
console.log("\nChecking idx advancement (5 probes, 300ms apart, BEFORE IMU enable):");
for (let t = 0; t < 5; t++) {
  replies.length = 0;
  await w(send([0x49])); await Bun.sleep(300);
  const p = replies.find(r => r.tag === 'I')?.data;
  if (p) console.log(`  idx=${p[6]} flags=0x${p[7]?.toString(16).padStart(2,"0")}`);
  else console.log("  no reply");
}

// Enable IMU
console.log("\nEnabling IMU ('i')...");
await w(send([0x69])); await Bun.sleep(2000);

console.log("\nAfter IMU enable, checking idx advancement (10 probes, 300ms):");
for (let t = 0; t < 10; t++) {
  replies.length = 0;
  await w(send([0x49])); await Bun.sleep(300);
  const p = replies.find(r => r.tag === 'I')?.data;
  if (p) console.log(`  idx=${p[6]} flags=0x${p[7]?.toString(16).padStart(2,"0")}`);
  else console.log("  no reply");
}

// Now the key test: read the RING BASE (entry 0) by dumping memory at ring+0x10..0x48
// Since we can't do a generic memory read, let's check the PREVIOUS 'I' format which read from ring base.
// For a quick test, let me add a different approach — read the ring ptr and check entry 0 using the
// accel data that WAS working before (it read from ring+0x34 which is entry[0]+0x34 IF no header).

console.log("\n=== KEY TEST: raw SRAM ring dump via 'D' (reads entry[idx]) ===");
console.log("   idx is frozen at 10 → entry 10 is empty → THIS IS WHY EVERYTHING IS ZERO");
console.log("   We need to read from entry 0 instead (ring+0x10 for flags, ring+0x34 for accel).");
console.log("   The OLD code that worked used ring+0x10 directly without idx offset.");

// Dump entry[idx]
replies.length = 0;
await w(send([0x44])); await Bun.sleep(500);
const d0 = replies.find(r => r.tag === 'D' && r.data[2] === 0)?.data;
const d1 = replies.find(r => r.tag === 'D' && r.data[2] === 1)?.data;
if (d0 && d1) {
  console.log(`\nEntry[${d0[3]}] (from idx):`);
  console.log(`  +00..0F: ${hex(d0, 4, 20)}`);
  console.log(`  +10..1F: ${hex(d0, 20, 36)}`);
  console.log(`  +20..2F: ${hex(d0, 36, 52)}`);
  console.log(`  +30..37: ${hex(d0, 52, 60)}`);
  console.log(`  +38..47: ${hex(d1, 4, 20)}`);
  console.log(`  +48..57: ${hex(d1, 20, 36)}`);
  console.log(`  +58..67: ${hex(d1, 36, 52)}`);
  console.log(`  +68..6F: ${hex(d1, 52, 60)}`);
}

console.log("\n⚡ NEXT STEP: Fix mode_ownanim.c to read from ring+offset (entry 0) not ring+idx*0x70+offset");
console.log("   The ring index is either stale or doesn't work the way we assumed.");

await s.close(); process.exit(0);
