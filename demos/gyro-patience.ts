import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 22 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });
// imu should already be ON from gyro-live.ts. Wait and sample every 2s for 30s.
console.log("waiting for gyro cal to appear (calibration may take 10-30s)...\nTURN/TILT head gently.");
for (let t = 0; t < 15; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(2000);
  if (!latest) continue;
  const flags = latest[7]!, gx = i16at(latest, 16)/100, gy = i16at(latest, 18)/100, gz = i16at(latest, 20)/100;
  const ax = i16at(latest, 10)/100, ay = i16at(latest, 12)/100, az = i16at(latest, 14)/100;
  console.log(`  ${(t*2).toString().padStart(2)}s: flags=0x${flags.toString(16)} gyro=[${gx},${gy},${gz}] accel=[${ax},${ay},${az}]`);
  if (gx !== 0 || gy !== 0 || gz !== 0) { console.log("  *** GYRO IS ALIVE ***"); break; }
}
await s.close(); process.exit(0);
