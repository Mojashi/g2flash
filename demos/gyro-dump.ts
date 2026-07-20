#!/usr/bin/env bun
// gyro-dump.ts — Load payload, enable gyro, dump full ring entry hex to find where gyro data lives
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const hex = (b: Uint8Array, from = 0, to?: number) => Buffer.from(b.subarray(from, to)).toString("hex");
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const f32at = (p: Uint8Array, o: number) => { const buf = new ArrayBuffer(4); const u8 = new Uint8Array(buf); u8[0]=p[o]!; u8[1]=p[o+1]!; u8[2]=p[o+2]!; u8[3]=p[o+3]!; return new Float32Array(buf)[0]!; };
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);

const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };

const dumps: Uint8Array[] = [];
const probes: Uint8Array[] = [];
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p[0] === 0xa7 && p[1] === 0x44) dumps.push(new Uint8Array(p));
  if (p[0] === 0xa7 && p[1] === 0x49) probes.push(new Uint8Array(p));
});

console.log(`Loading ${blob.length}B payload...`);
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);

console.log("Opening mode...");
await w(send([0x67])); await Bun.sleep(1500);

// Probe BEFORE IMU enable
console.log("\n=== BEFORE IMU enable ===");
dumps.length = 0; probes.length = 0;
await w(send([0x44])); // 'D' dump
await w(send([0x49])); // 'I' probe
await Bun.sleep(500);

if (probes.length > 0) {
  const p = probes[0]!;
  console.log(`  flags=0x${p[7]?.toString(16).padStart(2,"0")} idx=${p[6]} side=${p[5]}`);
  console.log(`  raw_gyro_i16: x=${i16at(p,8)} y=${i16at(p,22)} z=${i16at(p,24)}`);
  console.log(`  accel_cal: [${i16at(p,10)/100}, ${i16at(p,12)/100}, ${i16at(p,14)/100}]`);
  console.log(`  gyro_cal_f: [${i16at(p,16)/100}, ${i16at(p,18)/100}, ${i16at(p,20)/100}]`);
}

if (dumps.length >= 2) {
  const d0 = dumps.find(d => d[2] === 0)!;
  const d1 = dumps.find(d => d[2] === 1)!;
  console.log(`  entry[${d0[3]}] raw hex (0x70 bytes):`);
  // Offset 0x00-0x37 from chunk0
  console.log(`    +00: ${hex(d0, 4, 20)}`);  // 0x00-0x0F
  console.log(`    +10: ${hex(d0, 20, 36)}`);  // 0x10-0x1F (flags, accel_raw, gyro_raw)
  console.log(`    +20: ${hex(d0, 36, 52)}`);  // 0x20-0x2F (gyro_fused, quat)
  console.log(`    +30: ${hex(d0, 52, 60)}`);  // 0x30-0x37
  // Offset 0x38-0x6F from chunk1
  console.log(`    +38: ${hex(d1, 4, 20)}`);
  console.log(`    +48: ${hex(d1, 20, 36)}`);
  console.log(`    +58: ${hex(d1, 36, 52)}`);
  console.log(`    +68: ${hex(d1, 52, 60)}`);

  // Parse known fields from raw entry bytes
  const entry = new Uint8Array(112);
  entry.set(d0.subarray(4, 60), 0); // bytes 0-55
  entry.set(d1.subarray(4, 60), 56); // bytes 56-111
  console.log(`\n  Parsed fields:`);
  console.log(`    flags(+0x10): 0x${entry[0x10]?.toString(16).padStart(2,"0")}`);
  console.log(`    accel_raw_i16(+0x12): [${i16at(entry,0x12)}, ${i16at(entry,0x14)}, ${i16at(entry,0x16)}]`);
  console.log(`    gyro_chip_raw_i16(+0x18): [${i16at(entry,0x18)}, ${i16at(entry,0x1a)}, ${i16at(entry,0x1c)}]`);
  console.log(`    gyro_fused_i16(+0x1e): [${i16at(entry,0x1e)}, ${i16at(entry,0x20)}, ${i16at(entry,0x22)}]`);
  console.log(`    accel_cal_f(+0x34): [${f32at(entry,0x34).toFixed(4)}, ${f32at(entry,0x38).toFixed(4)}, ${f32at(entry,0x3c).toFixed(4)}]`);
  console.log(`    gyro_chip_cal_f(+0x40): [${f32at(entry,0x40).toFixed(4)}, ${f32at(entry,0x44).toFixed(4)}, ${f32at(entry,0x48).toFixed(4)}]`);
  console.log(`    gyro_fused_cal_f(+0x4c): [${f32at(entry,0x4c).toFixed(4)}, ${f32at(entry,0x50).toFixed(4)}, ${f32at(entry,0x54).toFixed(4)}]`);
  console.log(`    orient_f(+0x68): [${f32at(entry,0x68).toFixed(4)}, ${f32at(entry,0x6c).toFixed(4)}, ${f32at(entry,0x70).toFixed(4)}]`);
}

// Enable IMU
console.log("\n=== Enabling IMU ('i' = StartIMUCompassFunc) ===");
await w(send([0x69])); await Bun.sleep(3000);

// Probe AFTER IMU enable — multiple times while moving head
console.log("\n=== AFTER IMU enable (MOVE HEAD) ===");
for (let t = 0; t < 5; t++) {
  dumps.length = 0; probes.length = 0;
  await w(send([0x44])); await w(send([0x49])); await Bun.sleep(400);

  if (probes.length > 0) {
    const p = probes[0]!;
    console.log(`\n  [${t}] flags=0x${p[7]?.toString(16).padStart(2,"0")} idx=${p[6]}`);
    console.log(`      raw_gyro_i16: x=${i16at(p,8)} y=${i16at(p,22)} z=${i16at(p,24)}`);
    console.log(`      accel_cal: [${i16at(p,10)/100}, ${i16at(p,12)/100}, ${i16at(p,14)/100}]`);
    console.log(`      gyro_cal_f: [${i16at(p,16)/100}, ${i16at(p,18)/100}, ${i16at(p,20)/100}]`);
  }

  if (dumps.length >= 2) {
    const d0 = dumps.find(d => d[2] === 0)!;
    const d1 = dumps.find(d => d[2] === 1)!;
    const entry = new Uint8Array(112);
    entry.set(d0.subarray(4, 60), 0);
    entry.set(d1.subarray(4, 60), 56);

    // Check ALL fields for non-zero data
    const nonzeroFields: string[] = [];
    for (let off = 0x10; off < 0x70; off += 2) {
      const v = i16at(entry, off);
      if (v !== 0) nonzeroFields.push(`+0x${off.toString(16)}=${v}`);
    }
    console.log(`      non-zero i16 fields: ${nonzeroFields.length > 0 ? nonzeroFields.join(", ") : "(all zero except parsed above)"}`);

    // Show hex of gyro region specifically
    console.log(`      +18..1d (gyro_chip_raw): ${hex(entry, 0x18, 0x1e)}`);
    console.log(`      +1e..23 (gyro_fused_raw): ${hex(entry, 0x1e, 0x24)}`);
    console.log(`      +40..4b (gyro_chip_cal_f): ${hex(entry, 0x40, 0x4c)}`);
  }
}

// Also try reading multiple entries (not just current idx)
console.log("\n=== Scan ALL 20 ring entries for any gyro data ===");
// We can't dump all 20 via 'D', but we can quickly check if index is changing
for (let t = 0; t < 5; t++) {
  probes.length = 0;
  await w(send([0x49])); await Bun.sleep(150);
  if (probes.length > 0) {
    const p = probes[0]!;
    process.stdout.write(`  idx=${p[6]} flags=0x${p[7]?.toString(16).padStart(2,"0")} `);
  }
}
console.log("");

await s.close(); process.exit(0);
