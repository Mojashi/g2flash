import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o+1]! << 8) | (p[o+2]! << 16) | (p[o+3]! << 24)) >>> 0;
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 20 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });
// assume already loaded+open+imu from full-test.ts
console.log("reading 'I' probe 20x rapidly (200ms apart). NOD YOUR HEAD up/down to test pitch:\n");
console.log("  #  flags  accel_x  accel_y  accel_z  orient_x orient_y orient_z  angY angX");
for (let t = 0; t < 20; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(200);
  if (!latest || latest.length < 22) { console.log(`  ${t}: miss`); continue; }
  const p = latest;
  const flags = p[7]!;
  const ax = i16at(p,10)/100, ay = i16at(p,12)/100, az = i16at(p,14)/100;
  const ox = i16at(p,16)/100, oy = i16at(p,18)/100, oz = i16at(p,20)/100;
  console.log(`  ${t.toString().padStart(2)}  0x${flags.toString(16).padStart(2,"0")}   ${ax.toFixed(2).padStart(6)} ${ay.toFixed(2).padStart(6)} ${az.toFixed(2).padStart(6)}   ${ox.toFixed(2).padStart(6)} ${oy.toFixed(2).padStart(6)} ${oz.toFixed(2).padStart(6)}   ${p[8]!.toString().padStart(3)} ${p[9]!.toString().padStart(3)}`);
}
await s.close(); process.exit(0);
