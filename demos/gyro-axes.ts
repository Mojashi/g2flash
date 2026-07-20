import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o+1]! << 8) | (p[o+2]! << 16) | (p[o+3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };

// Read gyro cal floats directly from ring+0x40/0x44/0x48 via a custom 'I' that returns them.
// Current 'I' only returns accel+orient, not gyro. So we read the raw ring bytes instead.
// Simpler: just print 3 float32 from ring+0x40..0x4b in the same probe by extending it.
// Actually, let's use a separate dedicated command. But for now, modify the test to just
// observe which axis of the MODEL responds to which head movement.

// Plan: send 'I' and also manually read the ring gyro floats by sending them as a custom probe.
// Since we can't easily extend the probe, let's observe the OUTPUT angles (angY, angX) while
// doing specific movements:

let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 20 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });

console.log("=== AXIS CALIBRATION: 3 phases, 3s each ===");
console.log("Phase 1: KEEP STILL (baseline)");
console.log("Phase 2: NOD up/down only (pitch)");
console.log("Phase 3: TURN left/right only (yaw)\n");

for (const [phase, label] of [[0,"STILL"],[1,"NOD"],[2,"TURN"]] as const) {
  console.log(`--- ${label} (3s) ---`);
  const samples: {angY: number, angX: number}[] = [];
  for (let t = 0; t < 15; t++) {
    latest = null; await w(send([0x49])); await Bun.sleep(200);
    if (!latest) continue;
    samples.push({ angY: latest[8]!, angX: latest[9]! });
  }
  if (samples.length < 2) { console.log("  (no data)"); continue; }
  const dY = samples.map((s, i) => i > 0 ? Math.abs(s.angY - samples[i-1]!.angY) : 0);
  const dX = samples.map((s, i) => i > 0 ? Math.abs(s.angX - samples[i-1]!.angX) : 0);
  // handle wraparound: if delta > 128, it wrapped
  const fix = (d: number) => d > 128 ? 256 - d : d;
  const totalDY = dY.reduce((a, b) => a + fix(b), 0);
  const totalDX = dX.reduce((a, b) => a + fix(b), 0);
  console.log(`  angY total movement: ${totalDY}  angX total movement: ${totalDX}`);
  console.log(`  angY range: ${Math.min(...samples.map(s=>s.angY))}..${Math.max(...samples.map(s=>s.angY))}  angX range: ${Math.min(...samples.map(s=>s.angX))}..${Math.max(...samples.map(s=>s.angX))}`);
}
await s.close(); process.exit(0);
