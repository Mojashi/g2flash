import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o+1]! << 8) | (p[o+2]! << 16) | (p[o+3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 20 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });

// imu should be on from full-test. Toggle ON just in case
await w(send([0x69])); await Bun.sleep(500);
// check state
latest = null; await w(send([0x49])); await Bun.sleep(500);
if (latest) console.log(`imu_on=${latest[2]} side=${latest[5]} flags=0x${latest[7]?.toString(16)}`);

// Now read the gyro cal floats directly: ring+0x40,0x44,0x48
// We don't have those in the 'I' probe. Read them via imu-diff style: 
// Use the probe to get accel (ring+0x34..0x3c) — if accel changes, the ring is alive.
// Also look at the rot matrix values. We can infer those from the SYNC reply.
// But simpler: just check if the rot matrix in ctx changes.
// Let's add a tiny check: are the gyro floats actually nonzero?
// We know ring+0x48 (gyro z) drove yaw before. Read ring raw:
console.log("\nreading ring gyro cal floats (0x40,0x44,0x48) 10x while turning head:");
for (let t = 0; t < 10; t++) {
  // We can't read arbitrary ring offsets with current 'I'. But accel at ring+0x34..0x3c is in the probe.
  // Let's just look at whether angY/angX (the computed values from read_imu_matrix) change.
  latest = null; await w(send([0x49])); await Bun.sleep(300);
  if (!latest) { console.log(`  ${t}: miss`); continue; }
  const imu_on = latest[2], flags = latest[7], angY = latest[8], angX = latest[9];
  const ax = (latest[10]! | (latest[11]! << 8)); const axi = ax > 32767 ? ax - 65536 : ax;
  const ay = (latest[12]! | (latest[13]! << 8)); const ayi = ay > 32767 ? ay - 65536 : ay;
  const az = (latest[14]! | (latest[15]! << 8)); const azi = az > 32767 ? az - 65536 : az;
  console.log(`  ${t}: imu=${imu_on} flags=0x${flags.toString(16)} angY=${angY} angX=${angX} accel=[${axi/100},${ayi/100},${azi/100}]`);
}
await s.close(); process.exit(0);
