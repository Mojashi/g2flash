import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o+1]! << 8) | (p[o+2]! << 16) | (p[o+3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 100 && p[0] === 0xa7 && p[1] !== 0x6b) latest = p; });

console.log("Reading accel x/y/z every 500ms for 20s.");
console.log("INSTRUCTIONS: keep still 5s, then TILT LEFT/RIGHT 5s, then NOD UP/DOWN 5s, then TURN HEAD LEFT/RIGHT 5s.\n");
const t0 = performance.now();
for (let i = 0; i < 40; i++) {
  latest = null; await w(send([0x49])); await Bun.sleep(500);
  if (!latest || latest.length < 16) { console.log(`${((performance.now()-t0)/1000).toFixed(1)}s: miss`); continue; }
  // ring starts at byte 2; accel floats at ring+0x34 = word 13 from ring start
  const x = f32(u32at(latest, 2 + 0x34));
  const y = f32(u32at(latest, 2 + 0x38));
  const z = f32(u32at(latest, 2 + 0x3c));
  const phase = i < 10 ? "STILL" : i < 20 ? "TILT L/R" : i < 30 ? "NOD" : "TURN";
  console.log(`${((performance.now()-t0)/1000).toFixed(1)}s [${phase}]  x=${x.toFixed(3)}  y=${y.toFixed(3)}  z=${z.toFixed(3)}`);
}
await s.close(); process.exit(0);
