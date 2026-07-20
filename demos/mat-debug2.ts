import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 20 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });

// ensure imu ON: toggle until imu_on==1
for (let attempt = 0; attempt < 4; attempt++) {
  await w(send([0x69])); await Bun.sleep(800);
  latest = null; await w(send([0x49])); await Bun.sleep(500);
  if (latest && latest[2] === 1) { console.log(`imu_on=1 after ${attempt+1} toggle(s)`); break; }
  console.log(`  attempt ${attempt+1}: imu_on=${latest?.[2]}`);
}

console.log("\nreading angY/angX 10x while TURNING HEAD:");
for (let t = 0; t < 10; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(300);
  if (!latest) { console.log(`  ${t}: miss`); continue; }
  console.log(`  ${t}: imu=${latest[2]} angY=${latest[8]} angX=${latest[9]} flags=0x${latest[7]?.toString(16)}`);
}
await s.close(); process.exit(0);
