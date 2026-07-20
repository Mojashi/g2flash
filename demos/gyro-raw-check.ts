import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o+1]! << 8) | (p[o+2]! << 16) | (p[o+3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 20 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });
// probe returns: [2]=imu_on [5]=side [7]=flags [8]=aY [9]=aX [10..15]=accel_i16 [16..21]=orient_i16
// But we need gyro cal floats! The 'I' probe doesn't include them.
// Quick: read rot matrix from the 'I' probe to see if it's changing.
// Actually, let's just look at imu_on and rot_init status via the mark replies.
console.log("sending 'i' to enable IMU, then checking rot values...");
await w(send([0x69])); await Bun.sleep(1500);
// poll 'I' to see imu_on state
for (let t = 0; t < 5; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(400);
  if (!latest) { console.log(`  ${t}: miss`); continue; }
  console.log(`  ${t}: imu_on=${latest[2]} side=${latest[5]} flags=0x${latest[7]?.toString(16)}`);
}
await s.close(); process.exit(0);
