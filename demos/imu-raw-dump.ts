#!/usr/bin/env bun
// imu-raw-dump.ts — enable IMU with a high reportFrq and dump EVERY raw sid-0xe0 frame (not just the
// ones that match the narrowly-parsed IMU_Report_Data). This reveals the TRUE delivery rate, the
// frame diversity (gyro? quat? other EventTypes?), and whether reportFrq actually controls it.
import { G2Session, buildCreateStartUpPageContainer, buildHeartbeat, buildShutDown } from "g2-kit/ble";

function varint(n: number): number[] { const o: number[] = []; let v = n >>> 0; do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; o.push(b); } while (v); return o; }
function key(f: number, wt: number): number[] { return varint((f << 3) | wt); }
function submsg(f: number, body: number[]): number[] { return [...key(f, 2), ...varint(body.length), ...body]; }
function vfield(f: number, val: number): number[] { return [...key(f, 0), ...varint(val)]; }
const CMD_OPEN_IMU = 19;
function buildImuCtrl(en: number, freq: number, magic: number): Uint8Array {
  const imuCtrl = [...vfield(1, en), ...vfield(2, freq)];
  return new Uint8Array([...vfield(1, CMD_OPEN_IMU), ...vfield(2, magic), ...submsg(22, imuCtrl)]);
}
const hex = (b: Uint8Array) => Buffer.from(b).toString("hex");
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;

const FREQ = Number(process.argv[2] ?? 100);
const SECS = Number(process.argv[3] ?? 5);

const session = await G2Session.open({ quiet: true });
console.log(`connected. enabling IMU at reportFrq=${FREQ}, dumping ALL sid-0xe0 frames for ${SECS}s...`);

const cre = buildCreateStartUpPageContainer({ name: "imu", items: ["IMU raw"] });
await session.sendPb(0xe0, cre.pb, cre.magic, { ackTimeoutMs: 3000 }).catch(() => null);
const hb = setInterval(() => { const h = buildHeartbeat(); session.sendPb(0xe0, h.pb, h.magic, { ackTimeoutMs: 1500 }).catch(() => {}); }, 3000);
const magic = 88;
await session.sendPb(0xe0, buildImuCtrl(1, FREQ, magic), magic, { ackTimeoutMs: 3000 }).catch(() => null);

let count = 0;
const t0 = performance.now();
session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok || frame.sid !== 0xe0) return;
  count++;
  const dt = ((performance.now() - t0) / 1000).toFixed(2);
  // print first 30, then every 50th
  if (count <= 30 || count % 50 === 0) {
    console.log(`[${dt}s #${count} arm=${arm}] len=${frame.pb.length} pb=${hex(frame.pb).slice(0, 120)}${frame.pb.length > 60 ? "..." : ""}`);
  }
});

await Bun.sleep(SECS * 1000);
const elapsed = (performance.now() - t0) / 1000;
clearInterval(hb);
try { await session.sendPb(0xe0, buildImuCtrl(0, 0, (magic + 1) & 0xff), (magic + 1) & 0xff, { ackTimeoutMs: 1500 }); } catch {}
try { const sd = buildShutDown(); await session.sendPb(0xe0, sd.pb, sd.magic, { ackTimeoutMs: 1500 }); } catch {}
await session.close();
console.log(`\n=== total: ${count} frames in ${elapsed.toFixed(1)}s = ${(count / elapsed).toFixed(1)} Hz on sid 0xe0 ===`);
process.exit(0);
