import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 20 && p[0] === 0xa7 && p[1] === 0x49) latest = p;
  if (p.length >= 2 && p[0] === 0xa7 && p[1] === 0x69) console.log(`  mark 'i': val=${p[2]}`); });
console.log("toggling 'i' 4 times, checking imu_on each time:");
for (let t = 0; t < 4; t++) {
  await w(send([0x69])); await Bun.sleep(500);
  latest = null; await w(send([0x49])); await Bun.sleep(500);
  if (latest) console.log(`  toggle ${t+1}: imu_on=${latest[2]} side=${latest[5]}`);
  else console.log(`  toggle ${t+1}: no reply`);
}
await s.close(); process.exit(0);
