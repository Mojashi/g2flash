#!/usr/bin/env bun
// anim-drive.ts — drive mode_anim: keep ONE BLE connection open and send RT_OP_SEND 'n'
// (next frame) at a paced interval. The payload draws + jbd_flush per frame from the safe
// BLE-RX context. Usage: bun anim-drive.ts [frames] [frame_ms]
import { G2Session } from "g2-kit/ble";

const RUNTIME_SID = 0x7b;
const frames = Number(process.argv[2] ?? 240);
const frameMs = Number(process.argv[3] ?? 33);

function sendFrame(op: number): Uint8Array { return new Uint8Array([0x03, 0x01, op]); } // RT_OP_SEND mode=1 <op>

const session = await G2Session.open({ quiet: true });
console.log(`connected. animating ${frames} frames @ ${frameMs}ms (~${Math.round(1000 / frameMs)}fps target)`);
let seq = 1;
// reset to frame 0
await session.sendPb(RUNTIME_SID, sendFrame(0x72 /* 'r' */), seq++ & 0xff, { arm: "R", ackTimeoutMs: 200 }).catch(() => null);

const t0 = Date.now();
for (let i = 0; i < frames; i++) {
  const { ack } = await session.sendPbPipelined(RUNTIME_SID, sendFrame(0x6e /* 'n' */), seq++ & 0xff, { arm: "R" });
  ack.catch(() => null);
  await Bun.sleep(frameMs);
  if (i % 30 === 0) process.stdout.write(`\r  frame ${i}/${frames}  ${((Date.now() - t0) / 1000).toFixed(1)}s`);
}
const dt = (Date.now() - t0) / 1000;
console.log(`\ndone: ${frames} frames in ${dt.toFixed(1)}s = ${(frames / dt).toFixed(1)} fps effective`);
await session.close();
process.exit(0);
