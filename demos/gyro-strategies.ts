#!/usr/bin/env bun
// gyro-strategies.ts — Test multiple gyro enable strategies to find what works.
// Each strategy is tried in sequence, with IMU state probed before and after.
// Usage: bun run demos/gyro-strategies.ts [strategy]
//   strategy: all (default), P, H, J, K, L, i
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, BIN = "../obj/mode_ownanim.text.bin", FR = 225;
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const frag = (i: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(5 + d.length); f[0] = 1; f[1] = MODE; f[2] = i & 0xff; f[3] = (i >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, 5); return f; };
const act = (l: number, c: number) => Uint8Array.from([2, MODE, l & 0xff, (l >>> 8) & 0xff, (l >>> 16) & 0xff, (l >>> 24) & 0xff, c & 0xff, (c >>> 8) & 0xff, (c >>> 16) & 0xff, (c >>> 24) & 0xff]);
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const i16at = (p: Uint8Array, o: number) => { const v = p[o]! | (p[o + 1]! << 8); return v > 32767 ? v - 65536 : v; };
const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url))); const crc = crc32(blob);

const strategy = process.argv[2] || "all";

const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };

let latest: Uint8Array | null = null;
s.onRawFrame((f: any) => { if (!f.ok || f.sid !== SID) return; const p = f.pb;
  if (p.length >= 22 && p[0] === 0xa7 && p[1] === 0x49) latest = p;
});

async function probeIMU(label: string, count = 5, intervalMs = 300): Promise<boolean> {
  console.log(`  [${label}] probing ${count}× @ ${intervalMs}ms:`);
  let hasGyro = false;
  for (let t = 0; t < count; t++) {
    latest = null; await w(send([0x49])); await Bun.sleep(intervalMs);
    if (!latest) { console.log(`    ${t}: no reply`); continue; }
    const flags = latest[7]!;
    const gx = i16at(latest, 16) / 100, gy = i16at(latest, 18) / 100, gz = i16at(latest, 20) / 100;
    const ax = i16at(latest, 10) / 100, ay = i16at(latest, 12) / 100, az = i16at(latest, 14) / 100;
    const gyroNonZero = gx !== 0 || gy !== 0 || gz !== 0;
    if (gyroNonZero) hasGyro = true;
    console.log(`    ${t}: flags=0x${flags.toString(16).padStart(2,"0")} gyro=[${gx.toFixed(2)},${gy.toFixed(2)},${gz.toFixed(2)}] accel=[${ax.toFixed(2)},${ay.toFixed(2)},${az.toFixed(2)}] ${gyroNonZero ? "✓ GYRO!" : ""}`);
  }
  return hasGyro;
}

async function freshLoad() {
  console.log(`\n--- Fresh load (${blob.length}B)...`);
  await w(Uint8Array.from([4])); await Bun.sleep(300);
  const n = Math.ceil(blob.length / FR);
  for (let i = 0; i < n; i++) { await w(frag(i, i === n - 1, blob.subarray(i * FR, Math.min((i + 1) * FR, blob.length)))); await Bun.sleep(14); }
  await w(act(blob.length, crc)); await Bun.sleep(400);
  console.log("  loaded.");
}

async function testStrategy(name: string, desc: string, cmds: number[][], delays: number[]) {
  console.log(`\n${"=".repeat(60)}`);
  console.log(`STRATEGY ${name}: ${desc}`);
  console.log(`${"=".repeat(60)}`);
  await freshLoad();

  for (let i = 0; i < cmds.length; i++) {
    const cmd = cmds[i]!;
    const delay = delays[i] ?? 500;
    const cmdName = String.fromCharCode(cmd[0]!);
    console.log(`  → sending '${cmdName}' then wait ${delay}ms...`);
    await w(send(cmd)); await Bun.sleep(delay);
  }

  // probe immediately
  const quick = await probeIMU("immediate", 3, 200);
  if (quick) { console.log(`  ★★★ STRATEGY ${name} WORKS (immediate) ★★★`); return true; }

  // wait more and probe again (some approaches are async)
  console.log("  waiting 3s for async completion...");
  await Bun.sleep(3000);
  const delayed = await probeIMU("after-3s", 5, 400);
  if (delayed) { console.log(`  ★★★ STRATEGY ${name} WORKS (after delay) ★★★`); return true; }

  // wait even more (5s total extra)
  console.log("  waiting 5s more...");
  await Bun.sleep(5000);
  const late = await probeIMU("after-8s", 5, 400);
  if (late) { console.log(`  ★★★ STRATEGY ${name} WORKS (slow startup) ★★★`); return true; }

  console.log(`  ✗ Strategy ${name} did NOT produce gyro data.`);
  return false;
}

// Strategy definitions: [commands_in_order], [delay_after_each_ms]
const STRATEGIES: Record<string, { desc: string; cmds: number[][]; delays: number[] }> = {
  "i": {
    desc: "Baseline: open → barrier → 'i' (StartIMUCompassFunc after display_startup)",
    cmds: [[0x67]/*g*/, [0x6d]/*m*/, [0x69]/*i*/],
    delays: [1500, 500, 500],
  },
  "i-long": {
    desc: "Same as 'i' but with 5s delay after open (let auto-brightness reconfig finish)",
    cmds: [[0x67]/*g*/, [0x6d]/*m*/],
    delays: [5000, 500],
  },
  "P-before": {
    desc: "PRE-IMU: call StartIMUCompassFunc BEFORE open (gyro active during reconfig)",
    cmds: [[0x50]/*P*/, [0x67]/*g*/, [0x6d]/*m*/],
    delays: [500, 1500, 500],
  },
  "H": {
    desc: "hub_close(4) + delay + StartIMUCompassFunc (kill auto-brightness first)",
    cmds: [[0x67]/*g*/, [0x6d]/*m*/, [0x48]/*H*/],
    delays: [1500, 500, 2000], // H itself has 500ms internal busywait
  },
  "J": {
    desc: "Raw bhi260_sensor_enable(ctx, mode=0/1, {1,1,1}) — bypass hub entirely",
    cmds: [[0x67]/*g*/, [0x6d]/*m*/, [0x4a]/*J*/],
    delays: [1500, 500, 500],
  },
  "K": {
    desc: "hub_open(2) only — just role activation, might trigger full reconfig WITH gyro",
    cmds: [[0x67]/*g*/, [0x6d]/*m*/, [0x4b]/*K*/],
    delays: [1500, 500, 500],
  },
  "L": {
    desc: "FULL: hub_close(4)+hub_close(5)+1s delay+hub_open(2)+param_config — clean slate",
    cmds: [[0x67]/*g*/, [0x6d]/*m*/, [0x4c]/*L*/],
    delays: [1500, 500, 3000], // L has 1.5s internal busywait
  },
  "P-before-H": {
    desc: "Pre-IMU THEN open THEN hub_close(4)+StartIMU (combine P and H)",
    cmds: [[0x50]/*P*/, [0x67]/*g*/, [0x6d]/*m*/, [0x48]/*H*/],
    delays: [500, 1500, 500, 2000],
  },
};

// add 'i-long' — same as 'i' but probe gyro after a 5s wait
STRATEGIES["i-long"].cmds.push([0x69]/*i*/);
STRATEGIES["i-long"].delays.push(500);

console.log(`\nGyro Strategy Tester — testing: ${strategy === "all" ? Object.keys(STRATEGIES).join(", ") : strategy}`);
console.log(`Payload: ${blob.length}B, turn/nod head during probes for best results.\n`);

const results: Record<string, boolean> = {};
const toTest = strategy === "all" ? Object.keys(STRATEGIES) : [strategy];

for (const name of toTest) {
  const st = STRATEGIES[name];
  if (!st) { console.log(`Unknown strategy: ${name}`); continue; }
  results[name] = await testStrategy(name, st.desc, st.cmds, st.delays);
}

console.log(`\n${"=".repeat(60)}`);
console.log("RESULTS SUMMARY:");
for (const [name, ok] of Object.entries(results)) {
  console.log(`  ${ok ? "✓" : "✗"} ${name}: ${STRATEGIES[name]!.desc.split(":")[0]}`);
}
console.log(`${"=".repeat(60)}`);

await s.close(); process.exit(0);
