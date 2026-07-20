import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o+1]! << 8) | (p[o+2]! << 16) | (p[o+3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 22 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });
// imu should be ON from full-test.ts. If not, toggle.
for (let a = 0; a < 3; a++) { await w(send([0x69])); await Bun.sleep(500);
  latest=null; await w(send([0x49])); await Bun.sleep(500);
  if (latest && latest[2]===1) break; }
// Now read probe to see the raw gyro values (but the probe returns gyro cal float at r[16..21],
// which is 0). We need a different probe... OR check if angY/angX are changing.
console.log("checking angY/angX (should change when head moves if raw gyro works):");
console.log("  #  imu  angY  angX  flags  accel_x");
for (let t = 0; t < 20; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(200);
  if (!latest) continue;
  console.log(`  ${t.toString().padStart(2)}  ${latest[2]}    ${latest[8]?.toString().padStart(3)}   ${latest[9]?.toString().padStart(3)}   0x${latest[7]?.toString(16).padStart(2,"0")}   ${i16at(latest,10)/100}`);
}
await s.close(); process.exit(0);
