#!/usr/bin/env bun
// imu-drive.ts — feed the EXISTING BLE IMU stream (imu.ts-style) into mode_ownanim's 'F' command
// to drive the 3D rotation with your head. Even at ~1Hz it's worth seeing if the mapping feels right
// before investing in a higher-rate on-device path. Uses arm-L for 'F' (reaches both via barrier).
// Assumes the payload is already loaded+open+synced (stereo-go.ts first).
import { G2Session, buildCreateStartUpPageContainer, buildHeartbeat, buildShutDown } from "g2-kit/ble";

const SID_EH = 0xe0, SID_RT = 0x7b, MODE = 1;
function varint(n: number): number[] { const o: number[] = []; let v = n >>> 0; do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; o.push(b); } while (v); return o; }
function key(f: number, wt: number): number[] { return varint((f << 3) | wt); }
function submsg(f: number, body: number[]): number[] { return [...key(f, 2), ...varint(body.length), ...body]; }
function vfield(f: number, val: number): number[] { return [...key(f, 0), ...varint(val)]; }
function buildImuCtrl(en: number, freq: number, magic: number): Uint8Array {
  const imuCtrl = [...vfield(1, en), ...vfield(2, freq)];
  return new Uint8Array([...vfield(1, 19), ...vfield(2, magic), ...submsg(22, imuCtrl)]);
}
function parse(buf: Uint8Array): Map<number, { wt: number; u: number; b: Uint8Array }> {
  const m = new Map<number, { wt: number; u: number; b: Uint8Array }>(); let i = 0;
  while (i < buf.length) {
    let k = 0, s = 0; while (i < buf.length) { const c = buf[i++]!; k |= (c & 0x7f) << s; if (!(c & 0x80)) break; s += 7; }
    const field = k >>> 3, wt = k & 7;
    if (wt === 0) { let v = 0, ss = 0; while (i < buf.length) { const c = buf[i++]!; v += (c & 0x7f) * 2 ** ss; if (!(c & 0x80)) break; ss += 7; } m.set(field, { wt, u: v, b: new Uint8Array() }); }
    else if (wt === 2) { let len = 0, ss = 0; while (i < buf.length) { const c = buf[i++]!; len |= (c & 0x7f) << ss; if (!(c & 0x80)) break; ss += 7; } m.set(field, { wt, u: 0, b: buf.subarray(i, i + len) }); i += len; }
    else if (wt === 5) { m.set(field, { wt, u: buf[i] | (buf[i + 1] << 8) | (buf[i + 2] << 16) | (buf[i + 3] << 24), b: new Uint8Array() }); i += 4; }
    else if (wt === 1) { i += 8; } else break;
  }
  return m;
}
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
function decodeImu(pb: Uint8Array): { x: number; y: number; z: number } | null {
  for (const cand of [pb, pb.subarray(0, Math.max(0, pb.length - 2))]) {
    try {
      const top = parse(cand);
      const dev = top.get(13); if (!dev || dev.wt !== 2) continue;
      const sys = parse(dev.b).get(3); if (!sys || sys.wt !== 2) continue;
      const se = parse(sys.b);
      if (se.get(1)?.u === 8 && se.get(3)?.wt === 2) {
        const f = parse(se.get(3)!.b);
        return { x: f32(f.get(1)?.u ?? 0), y: f32(f.get(2)?.u ?? 0), z: f32(f.get(3)?.u ?? 0) };
      }
    } catch {}
  }
  return null;
}
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const setFrame = (a: number) => send([0x46, a & 0xff, (a >>> 8) & 0xff, (a >>> 16) & 0xff, (a >>> 24) & 0xff]);

const session = await G2Session.open({ quiet: true });
let seq = 1;
const w = async (sid: number, arm: "L" | "R", pb: Uint8Array) => {
  const { ack } = await session.sendPbPipelined(sid, pb, seq++ & 0xff, { arm }); ack.catch(() => null);
};

// enter EvenHub + enable IMU
console.log("entering EvenHub + enabling IMU at reportFrq=100...");
const cre = buildCreateStartUpPageContainer({ name: "imu", items: ["IMU head-track"] });
await session.sendPb(SID_EH, cre.pb, cre.magic, { ackTimeoutMs: 3000 }).catch(() => null);
const hb = setInterval(() => { const h = buildHeartbeat(); session.sendPb(SID_EH, h.pb, h.magic, { ackTimeoutMs: 1500 }).catch(() => {}); }, 3000);
const magic = 99;
await session.sendPb(SID_EH, buildImuCtrl(1, 100, magic), magic, { ackTimeoutMs: 3000 }).catch(() => null);

// on each IMU sample, convert to a rotation angle and push it to the payload
let angle = 0, imuCount = 0;
session.onRawFrame((frame, _raw, arm) => {
  if (!frame.ok || frame.sid !== SID_EH || arm !== "R") return;
  const imu = decodeImu(frame.pb);
  if (!imu) return;
  imuCount++;
  // roll -> Y-spin, pitch -> X-tumble; scale so tilting ~45deg → one full 256-step turn
  const roll = Math.atan2(imu.x, imu.z);     // radians, ~0 upright, +/- when tilting left/right
  const pitch = Math.atan2(imu.y, imu.z);    // radians, ~0 upright, +/- when nodding forward/back
  // map roll to the 256-step angle space (one full rotation = 256); scale so +/-90deg = +/-128
  angle = Math.round((roll / Math.PI) * 128 + 128) & 0xff;
  process.stdout.write(`\r  imu#${imuCount}  roll=${roll.toFixed(2)} pitch=${pitch.toFixed(2)} -> angle=${angle}   `);
});

// push the latest angle at ~15Hz
console.log("driving rotation from head IMU (Ctrl-C to stop)...");
const driveLoop = setInterval(async () => {
  await w(SID_RT, "L", setFrame(angle));
}, 66);

// run for 30s then clean up
process.on("SIGINT", async () => { clearInterval(driveLoop); clearInterval(hb);
  try { await session.sendPb(SID_EH, buildImuCtrl(0, 0, (magic + 1) & 0xff), (magic + 1) & 0xff, { ackTimeoutMs: 1500 }); } catch {}
  try { const sd = buildShutDown(); await session.sendPb(SID_EH, sd.pb, sd.magic, { ackTimeoutMs: 1500 }); } catch {}
  await w(SID_RT, "L", send([0x41])); // 'A' release manual mode
  await session.close(); process.exit(0); });
await Bun.sleep(30000);
clearInterval(driveLoop); clearInterval(hb);
try { await session.sendPb(SID_EH, buildImuCtrl(0, 0, (magic + 1) & 0xff), (magic + 1) & 0xff, { ackTimeoutMs: 1500 }); } catch {}
await w(SID_RT, "L", send([0x41]));
await session.close(); process.exit(0);
