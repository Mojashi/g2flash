import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 32 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });
// ensure IMU on
for (let a = 0; a < 3; a++) { await w(send([0x69])); await Bun.sleep(500);
  latest=null; await w(send([0x49])); await Bun.sleep(500);
  if (latest && latest[2]===1) { console.log("imu_on=1"); break; } }
console.log("rot diagonal (Q12, identity=4096) + orient — TURN HEAD:");
for (let t = 0; t < 15; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(250);
  if (!latest || latest.length < 32) continue;
  const r0 = i16at(latest, 26), r4 = i16at(latest, 28), r8 = i16at(latest, 30);
  const ox = i16at(latest,16)/100, oy = i16at(latest,18)/100, oz = i16at(latest,20)/100;
  const rot_init = latest[2]; // imu_on
  console.log(`  ${t}: rot_diag=[${r0},${r4},${r8}] orient=[${ox.toFixed(1)},${oy.toFixed(1)},${oz.toFixed(1)}] imu=${latest[2]} flags=0x${latest[7]?.toString(16)}`);
}
await s.close(); process.exit(0);
