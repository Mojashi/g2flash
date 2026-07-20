import { G2Session } from "g2-kit/ble";
const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const u32at = (p: Uint8Array, o: number) => (p[o]! | (p[o+1]! << 8) | (p[o+2]! << 16) | (p[o+3]! << 24)) >>> 0;
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 100 && p[0] === 0xa7 && p[1] === 0x49) latest = p; });
function snap(): Uint32Array | null {
  if (!latest || latest.length < 114) return null;
  const v = new Uint32Array(28);
  for (let j = 0; j < 28; j++) v[j] = u32at(latest, 2 + j * 4);
  return v;
}
console.log("taking 8 snapshots 1s apart (TILT YOUR HEAD)...\n");
const all: (Uint32Array | null)[] = [];
for (let t = 0; t < 8; t++) {
  latest = null; await w(send([0x49])); await Bun.sleep(1000);
  all.push(snap());
  if (!snap) console.log(`  snap ${t}: miss`);
}
console.log("=== DIFF ===");
const ever = new Set<number>();
for (let t = 1; t < all.length; t++) {
  if (!all[t] || !all[t-1]) continue;
  const d: string[] = [];
  for (let j = 0; j < 28; j++) {
    if (all[t]![j] !== all[t-1]![j]) {
      d.push(`+0x${(j*4).toString(16).padStart(2,"0")}:${f32(all[t]![j]!).toFixed(3)}(was ${f32(all[t-1]![j]!).toFixed(3)})`);
      ever.add(j);
    }
  }
  console.log(`  ${t-1}->${t}: ${d.join("  ") || "(same)"}`);
}
console.log(`\nLIVE offsets: ${[...ever].sort((a,b)=>a-b).map(j=>`+0x${(j*4).toString(16).padStart(2,"0")}`).join(", ") || "none"}`);
await s.close(); process.exit(0);
