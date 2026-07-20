import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 20 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });

console.log("enabling IMU ('i')...");
await w(send([0x69])); await Bun.sleep(1500);
console.log("Phase 1: STILL 3s, Phase 2: NOD 3s, Phase 3: TURN 3s\n");
for (const [label] of [["STILL"],["NOD"],["TURN"]]) {
  console.log(`--- ${label} ---`);
  const samples: {y:number,x:number}[] = [];
  for (let t = 0; t < 15; t++) {
    latest = null; await w(send([0x49])); await Bun.sleep(200);
    if (!latest) continue;
    samples.push({y: latest[8]!, x: latest[9]!});
  }
  const fix = (d: number) => d > 128 ? 256 - d : d;
  const dY = samples.slice(1).reduce((a, s, i) => a + fix(Math.abs(s.y - samples[i]!.y)), 0);
  const dX = samples.slice(1).reduce((a, s, i) => a + fix(Math.abs(s.x - samples[i]!.x)), 0);
  console.log(`  angY movement: ${dY}  angX movement: ${dX}  (Y range ${Math.min(...samples.map(s=>s.y))}..${Math.max(...samples.map(s=>s.y))}, X range ${Math.min(...samples.map(s=>s.x))}..${Math.max(...samples.map(s=>s.x))})`);
}
await w(send([0x69])); // imu off
await s.close(); process.exit(0);
