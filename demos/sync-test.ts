#!/usr/bin/env bun
// sync-test.ts — verify the mode_ownanim wait-for-ack L/R barrier in ONE BLE session.
// Loads the payload to BOTH lenses, opens the mode, then measures the R vs L frame-counter
// delta over time: PHASE 1 (no sync -> expect the delta to drift) then PHASE 2 (barrier on
// via 'm' -> expect the delta to collapse and stay ~0). Reads counters numerically:
//   'k' (0x6b) -> R replies its frame [0xA7 6b f0 f1 f2 f3 side]
//   'l' (0x6c) -> L sends its frame over the peer link; R relays it [0xA7 6c f0 f1 f2 f3 side]
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";

const SID = 0x7b, MODE = 1;
const BIN = "../obj/mode_ownanim.text.bin";
const FRAG_DATA_MAX = 225, LOAD_HDR = 5;

const CRC_TAB = (() => { const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = CRC_TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const loadFrag = (idx: number, last: boolean, d: Uint8Array) => { const f = new Uint8Array(LOAD_HDR + d.length); f[0] = 1; f[1] = MODE; f[2] = idx & 0xff; f[3] = (idx >>> 8) & 0xff; f[4] = last ? 1 : 0; f.set(d, LOAD_HDR); return f; };
const activate = (len: number, crc: number) => { const f = new Uint8Array(10); f[0] = 2; f[1] = MODE; f[2] = len & 0xff; f[3] = (len >>> 8) & 0xff; f[4] = (len >>> 16) & 0xff; f[5] = (len >>> 24) & 0xff; f[6] = crc & 0xff; f[7] = (crc >>> 8) & 0xff; f[8] = (crc >>> 16) & 0xff; f[9] = (crc >>> 24) & 0xff; return f; };
const send = (data: number[]) => { const f = new Uint8Array(2 + data.length); f[0] = 3; f[1] = MODE; f.set(data, 2); return f; };
const u32 = (p: Uint8Array, o: number) => (p[o]! | (p[o + 1]! << 8) | (p[o + 2]! << 16) | (p[o + 3]! << 24)) >>> 0;

const blob = new Uint8Array(readFileSync(new URL(BIN, import.meta.url)));
const crc = crc32(blob);
const session = await G2Session.open({ quiet: true });
let seq = 1;
const write = async (arm: "L" | "R", pb: Uint8Array) => { const { ack } = await session.sendPbPipelined(SID, pb, seq++ & 0xff, { arm }); ack.catch(() => null); };

let lastR: number | null = null, lastL: number | null = null, activeR: number | null = null;
session.onRawFrame((f: any) => {
  if (!f.ok || f.sid !== SID) return; const p = f.pb; if (p.length < 2 || p[0] !== 0xa7) return;
  if (p[1] === 0x02) activeR = p[2];
  else if (p[1] === 0x6b && p.length >= 6) lastR = u32(p, 2);
  else if (p[1] === 0x6c && p.length >= 6) lastL = u32(p, 2);
});

async function upload(arm: "L" | "R") {
  const n = Math.ceil(blob.length / FRAG_DATA_MAX);
  for (let i = 0; i < n; i++) { await write(arm, loadFrag(i, i === n - 1, blob.subarray(i * FRAG_DATA_MAX, Math.min((i + 1) * FRAG_DATA_MAX, blob.length)))); await Bun.sleep(15); }
  await write(arm, activate(blob.length, crc)); await Bun.sleep(300);
}
async function readPair(): Promise<{ R: number | null; L: number | null }> {
  lastR = null; lastL = null;
  await write("R", send([0x6b])); await write("L", send([0x6c])); await Bun.sleep(500);
  return { R: lastR, L: lastL };
}
async function phase(label: string, n: number) {
  console.log(`\n=== ${label} ===`);
  const first: { R: number | null; L: number | null } = { R: null, L: null };
  for (let i = 0; i < n; i++) {
    const { R, L } = await readPair();
    const d = R != null && L != null ? R - L : null;
    if (first.R == null && R != null) first.R = R;
    if (first.L == null && L != null) first.L = L;
    console.log(`  t=${i}s  R=${R ?? "?"}  L=${L ?? "?"}  delta(R-L)=${d ?? "?"}`);
    await Bun.sleep(500);
  }
}

console.log(`payload ${blob.length}B crc=0x${crc.toString(16)}; RESET both (clear any stale/corrupt mode)...`);
await write("R", Uint8Array.from([4])); await write("L", Uint8Array.from([4])); await Bun.sleep(500);
console.log("loading to R...");
await upload("R"); console.log(`  R activate reply active=${activeR}`);
console.log("loading to L (L cannot reply; blind)...");
await upload("L");
console.log("opening mode on R and L ('g')...");
await write("R", send([0x67])); await write("L", send([0x67])); await Bun.sleep(1500);

await phase("PHASE 1: NO SYNC (baseline — expect delta to drift)", 8);
console.log("\nenabling barrier sync: 'm' -> R");
await write("R", send([0x6d])); await Bun.sleep(1500);
await phase("PHASE 2: BARRIER SYNC ON (expect delta ~0, stable)", 10);

console.log("\ndisabling sync + closing");
await write("R", send([0x6e])); await write("L", send([0x6e]));
await session.close(); process.exit(0);
