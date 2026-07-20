import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 20 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });
console.log("NOD your head strongly up/down. Reading accel y + computed angX:\n");
for (let t = 0; t < 20; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(300);
  if (!latest) continue;
  const ax = i16at(latest, 10)/100, ay = i16at(latest, 12)/100, az = i16at(latest, 14)/100;
  const angY = latest[8], angX = latest[9];
  const pitchR = az !== 0 ? ay / Math.abs(az) : 0;
  console.log(`  ${t}: ay=${ay.toFixed(2)} az=${az.toFixed(2)} pitchR=${pitchR.toFixed(3)} → angX=${angX} (expected: ${((Math.round(pitchR*384)+256)&255)})`);
}
await s.close(); process.exit(0);
