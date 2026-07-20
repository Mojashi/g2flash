#!/usr/bin/env bun
// imu-coexist-test.ts — does BLE IMU streaming survive switching the visible foreground app away
// from EvenHub to our own custom mode_ownanim? Enter EvenHub + enable IMU (like imu.ts), THEN open
// our own-mode as foreground (arm-L 'g') WITHOUT disabling IMU/leaving EvenHub, and count whether
// IMU frames keep arriving over the following seconds. This determines whether head-tracked 3D
// control is a simple "forward IMU samples into our running mode" or needs a harder on-device path.
import { G2Session, buildCreateStartUpPageContainer, buildHeartbeat } from "g2-kit/ble";

const SID_EVENHUB = 0xe0, SID_RT = 0x7b, MODE = 1;
function varint(n: number): number[] { const o: number[] = []; let v = n >>> 0; do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; o.push(b); } while (v); return o; }
function key(field: number, wt: number): number[] { return varint((field << 3) | wt); }
function submsg(field: number, body: number[]): number[] { return [...key(field, 2), ...varint(body.length), ...body]; }
function vfield(field: number, val: number): number[] { return [...key(field, 0), ...varint(val)]; }
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
const CMD_OPEN_IMU = 19;
function buildImuCtrl(en: number, freq: number, magic: number): Uint8Array {
  const imuCtrl = [...vfield(1, en), ...vfield(2, freq)];
  return new Uint8Array([...vfield(1, CMD_OPEN_IMU), ...vfield(2, magic), ...submsg(22, imuCtrl)]);
}
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
function decodeImu(pb: Uint8Array): { x: number; y: number; z: number } | null {
  for (const cand of [pb, pb.subarray(0, Math.max(0, pb.length - 2))]) {
    try {
      const top = parse(cand);
      const dev = top.get(13); if (!dev || dev.wt !== 2) continue;
      const sys = parse(dev.b).get(3); if (!sys || sys.wt !== 2) continue;
      const se = parse(sys.b);
      const et = se.get(1)?.u; const imu = se.get(3);
      if (et === 8 && imu && imu.wt === 2) { const f = parse(imu.b); return { x: f32(f.get(1)?.u ?? 0), y: f32(f.get(2)?.u ?? 0), z: f32(f.get(3)?.u ?? 0) }; }
    } catch {}
  }
  return null;
}
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);

const session = await G2Session.open({ quiet: true });
let imuCount = 0;
session.onRawFrame((frame, _raw, arm) => { if (!frame.ok || frame.sid !== SID_EVENHUB || arm !== "R") return; if (decodeImu(frame.pb)) imuCount++; });

console.log("entering EvenHub + enabling IMU...");
const cre = buildCreateStartUpPageContainer({ name: "imu", items: ["IMU probe"] });
await session.sendPb(SID_EVENHUB, cre.pb, cre.magic, { ackTimeoutMs: 3000 }).catch(() => null);
const hb = setInterval(() => { const h = buildHeartbeat(); session.sendPb(SID_EVENHUB, h.pb, h.magic, { ackTimeoutMs: 1500 }).catch(() => {}); }, 3000);
const magic = 77;
await session.sendPb(SID_EVENHUB, buildImuCtrl(1, 50, magic), magic, { ackTimeoutMs: 3000 }).catch(() => null);
await Bun.sleep(2000);
console.log(`  baseline (EvenHub foreground): ${imuCount} IMU samples in 2s`);

console.log("\nNOW opening our own-mode as foreground (arm-L 'g') WITHOUT leaving EvenHub/disabling IMU...");
let seq = 1000;
const w = async (pb: Uint8Array) => { const { ack } = await session.sendPbPipelined(SID_RT, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };
await w(send([0x67])); // 'g'
imuCount = 0;
await Bun.sleep(3000);
console.log(`  AFTER opening own-mode: ${imuCount} IMU samples in the next 3s`);
console.log(imuCount > 10 ? "  => IMU KEEPS STREAMING while our own-mode is foreground! (coexistence confirmed)"
                          : "  => IMU stopped/starved once foreground switched away.");

clearInterval(hb);
await session.close();
process.exit(0);
