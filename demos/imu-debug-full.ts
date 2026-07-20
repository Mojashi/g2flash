import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const hex = (b: Uint8Array) => Buffer.from(b).toString("hex");
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o+1]! << 8) | (p[o+2]! << 16) | (p[o+3]! << 24)) >>> 0;
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
// print ALL replies
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p[0] === 0xa7) {
    const op = String.fromCharCode(p[1]!);
    if (op === 'I') {
      console.log(`  <- 'I': imu_on=${p[2]} flags=0x${p[7]?.toString(16)} gx=${i16at(p,16)/100} gy=${i16at(p,18)/100} gz=${i16at(p,20)/100} accel=[${i16at(p,10)/100},${i16at(p,12)/100},${i16at(p,14)/100}]`);
    } else {
      console.log(`  <- '${op}': ${hex(p.subarray(2,6))}`);
    }
  }
});

console.log("1. fresh load...");
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);
console.log("2. open mode...");
await w(send([0x67])); await Bun.sleep(1000);
console.log("3. barrier ON...");
await w(send([0x6d])); await Bun.sleep(500);

console.log("4. probe BEFORE 'i':");
await w(send([0x49])); await Bun.sleep(500);

console.log("5. sending 'i' (IMU enable)...");
await w(send([0x69])); await Bun.sleep(1500);

console.log("6. probe AFTER 'i' (×5, 500ms apart):");
for (let t = 0; t < 5; t++) { await w(send([0x49])); await Bun.sleep(500); }

console.log("7. wait 3s then probe again:");
await Bun.sleep(3000);
for (let t = 0; t < 5; t++) { await w(send([0x49])); await Bun.sleep(500); }

await s.close(); process.exit(0);
