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
  if (p.length >= 20 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });

console.log("reset+load+open+sync+stereo+imu...");
await w(Uint8Array.from([4])); await Bun.sleep(300);
const n = Math.ceil(blob.length / FR);
for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
await w(act(blob.length, crc)); await Bun.sleep(400);
await w(send([0x67])); await Bun.sleep(1000);
await w(send([0x6d])); await Bun.sleep(500); // barrier
await w(send([0x64])); await Bun.sleep(500); // stereo
await w(send([0x69])); await Bun.sleep(1000); // imu

console.log("\npolling 'I' 8x (tilt head between reads):");
for (let t = 0; t < 8; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(600);
  if (!latest) { console.log(`  ${t}: no reply`); continue; }
  const p = latest;
  const imu_on=p[2], angY_stored=p[3], angX_stored=p[4], side=p[5], idx=p[6];
  const computed_aY=p[7], computed_aX=p[8];
  const ax=i16at(p,9)/100, ay=i16at(p,11)/100, az=i16at(p,13)/100;
  const sync_on=p[15], dirty=p[16], waiting=p[17], stereo=p[18];
  console.log(`  ${t}: side=${side} imu_on=${imu_on} angY=${computed_aY} angX=${computed_aX} stored_aY=${angY_stored} stored_aX=${angX_stored} accel=[${ax},${ay},${az}] idx=${idx} sync=${sync_on} wait=${waiting} stereo=${stereo}`);
}
await s.close(); process.exit(0);
