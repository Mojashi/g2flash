#!/usr/bin/env bun
// hub-draw.ts — test the "own the display" hypothesis: enter EvenHub mode (so the
// dashboard/LVGL compositor is no longer the foreground that overwrites the canvas),
// THEN hot-load + activate a loader payload that draws the framebuffer. If EvenHub's
// on-demand rendering leaves the canvas alone between updates, the payload's draw persists.
//
//   bun hub-draw.ts [payload.bin]   default ../obj/mode_selftest.text.bin
import { G2Session, buildCreateStartUpPageContainer, buildHeartbeat, buildShutDown } from "g2-kit/ble";
import { readFileSync } from "node:fs";

const RUNTIME_SID = 0x7b;
const CRC32_TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
function crc32(b: Uint8Array) { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = CRC32_TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; }
function loadFrag(idx: number, last: boolean, data: Uint8Array) { const f = new Uint8Array(5 + data.length); f[0] = 1; f[1] = 0; f[2] = idx & 0xff; f[3] = (idx >> 8) & 0xff; f[4] = last ? 1 : 0; f.set(data, 5); return f; }
function activate(len: number, crc: number) { const f = new Uint8Array(10); f[0] = 2; f[1] = 0; f[2] = len; f[3] = len >>> 8; f[4] = len >>> 16; f[5] = len >>> 24; f[6] = crc; f[7] = crc >>> 8; f[8] = crc >>> 16; f[9] = crc >>> 24; return f; }

const blob = new Uint8Array(readFileSync(process.argv[2] ?? "../obj/mode_selftest.text.bin"));
const session = await G2Session.open({ quiet: true });
session.onRawFrame((f) => { if (f.ok && f.sid === RUNTIME_SID && f.pb[0] === 0xa7) console.log(`«rt» ${Buffer.from(f.pb).toString("hex")}`); });

// 1) enter EvenHub mode + keep it alive
console.log("entering EvenHub mode...");
const cre = buildCreateStartUpPageContainer({ name: "draw", items: ["hot-load draw test"] });
await session.sendPb(0xe0, cre.pb, cre.magic, { ackTimeoutMs: 3000 }).catch(() => {});
const hb = setInterval(() => { const h = buildHeartbeat(); session.sendPb(0xe0, h.pb, h.magic, { ackTimeoutMs: 1500 }).catch(() => {}); }, 3000);
await new Promise((r) => setTimeout(r, 1000));

// 2) upload + activate the payload on sid 0x7b
console.log(`uploading ${blob.length}B payload...`);
const FRAG = 200; let idx = 0;
for (let off = 0; off < blob.length; off += FRAG) {
  const chunk = blob.subarray(off, Math.min(off + FRAG, blob.length));
  await session.sendPb(RUNTIME_SID, loadFrag(idx, off + FRAG >= blob.length, chunk), idx & 0xff, { arm: "R", ackTimeoutMs: 400 }).catch(() => {});
  idx++; await Bun.sleep(15);
}
const crc = crc32(blob);
console.log(`ACTIVATE len=${blob.length} crc32=0x${crc.toString(16).padStart(8, "0")} — WATCH THE LENS`);
await session.sendPb(RUNTIME_SID, activate(blob.length, crc), 0x50, { arm: "R", ackTimeoutMs: 3000 }).catch(() => {});

// 3) keep EvenHub alive so the draw can persist; watch ~10s
await new Promise((r) => setTimeout(r, 10000));

clearInterval(hb);
const sd = buildShutDown(); await session.sendPb(0xe0, sd.pb, sd.magic, { ackTimeoutMs: 1500 }).catch(() => {});
await session.close();
process.exit(0);
