#!/usr/bin/env bun
// imu.ts — enable the G2 head IMU stream over BLE and MEASURE its granularity.
//
// Sends an EvenHub OPEN_IMU request (sid 0xe0, Cmd=19 APP_REQUEST_OPEN_IMU_PACKET, with
// ImuCtrl{IMUReportEn=1, reportFrq=N}); the glasses then stream IMU_Report_Data{x,y,z}
// inside Sys_ItemEvent (EventType=8 IMU_DATA_REPORT). We timestamp every sample, then
// report the ACTUAL delivered rate (Hz) + per-axis value ranges so you can see the real
// resolution/units the BLE path exposes. Stops the stream on exit.
//
//   bun imu.ts [reportFrq] [seconds]     defaults: reportFrq=50, seconds=8
import { G2Session, buildCreateStartUpPageContainer, buildHeartbeat, buildShutDown } from "g2-kit/ble";

const reportFrq = Number(process.argv[2] ?? 50);
const seconds = Number(process.argv[3] ?? 8);

// ---- tiny protobuf codec (wire format) ----
function varint(n: number): number[] { const o: number[] = []; let v = n >>> 0; do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; o.push(b); } while (v); return o; }
function key(field: number, wt: number): number[] { return varint((field << 3) | wt); }
function submsg(field: number, body: number[]): number[] { return [...key(field, 2), ...varint(body.length), ...body]; }
function vfield(field: number, val: number): number[] { return [...key(field, 0), ...varint(val)]; }
// parse a message into {field -> {wt, u (varint), b (bytes slice)}} (last wins)
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
  const imuCtrl = [...vfield(1, en), ...vfield(2, freq)];       // ImuCtrl{IMUReportEn, reportFrq}
  return new Uint8Array([...vfield(1, CMD_OPEN_IMU), ...vfield(2, magic), ...submsg(22, imuCtrl)]);
}

// x/y/z are wire-type 5 (fixed32) carrying IEEE-754 float32 (normalized accel, ~g units)
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
// decode an incoming sid-0xe0 frame -> IMU {x,y,z} if it carries IMU_DATA_REPORT
function decodeImu(pb: Uint8Array): { x: number; y: number; z: number } | null {
  for (const cand of [pb, pb.subarray(0, Math.max(0, pb.length - 2))]) {
    try {
      const top = parse(cand);
      const dev = top.get(13); if (!dev || dev.wt !== 2) continue;      // DevEvent (SendDeviceEvent)
      const sys = parse(dev.b).get(3); if (!sys || sys.wt !== 2) continue; // SysEvent (Sys_ItemEvent)
      const se = parse(sys.b);
      const et = se.get(1)?.u;                                            // EventType
      const imu = se.get(3);                                              // IMUData
      if (et === 8 && imu && imu.wt === 2) {
        const f = parse(imu.b);
        return { x: f32(f.get(1)?.u ?? 0), y: f32(f.get(2)?.u ?? 0), z: f32(f.get(3)?.u ?? 0) };
      }
    } catch {}
  }
  return null;
}

function ts() { return performance.now(); }
const samples: { t: number; x: number; y: number; z: number }[] = [];
const magic = (Math.floor(Math.random() * 250) + 1) & 0xff;

const session = await G2Session.open({ quiet: true });
console.log(`connected. enabling IMU at reportFrq=${reportFrq}, capturing ${seconds}s...`);

const DEBUG = process.env.DEBUG === "1";
// both arms relay the same IMU event; count only the R arm so the rate isn't doubled.
session.onRawFrame((frame, _raw, arm) => {
  if (!frame.ok || frame.sid !== 0xe0 || arm !== "R") return;
  const imu = decodeImu(frame.pb);
  if (imu) { samples.push({ t: ts(), ...imu }); if (DEBUG) console.log(`  imu x=${imu.x.toFixed(3)} y=${imu.y.toFixed(3)} z=${imu.z.toFixed(3)} |v|=${Math.hypot(imu.x, imu.y, imu.z).toFixed(3)}`); }
});

// EvenHub sid-0xe0 app commands are only honored while an EvenHub container is foreground
// AND heartbeats keep it alive. So: enter EvenHub mode -> heartbeat -> OPEN_IMU.
console.log("entering EvenHub mode (CreateStartUpPageContainer)...");
const cre = buildCreateStartUpPageContainer({ name: "imu", items: ["IMU probe"] });
try { const a = await session.sendPb(0xe0, cre.pb, cre.magic, { ackTimeoutMs: 3000 }); console.log(`  create ack: ${a ? "YES" : "none"}`); } catch (e) { console.log("  create err", String(e)); }
const hb = setInterval(() => { const h = buildHeartbeat(); session.sendPb(0xe0, h.pb, h.magic, { ackTimeoutMs: 1500 }).catch(() => {}); }, 3000);

console.log(`sending OPEN_IMU (Cmd=${CMD_OPEN_IMU}) reportFrq=${reportFrq} ...`);
try { const ack = await session.sendPb(0xe0, buildImuCtrl(1, reportFrq, magic), magic, { ackTimeoutMs: 3000 }); console.log(`  enable ack: ${ack ? "YES cmd=" + parse(ack.pb).get(1)?.u : "none (timeout)"}`); } catch (e) { console.log("  enable err", String(e)); }
const t0 = ts();
await new Promise((r) => setTimeout(r, seconds * 1000));
const t1 = ts();

// disable IMU + leave EvenHub mode
clearInterval(hb);
try { await session.sendPb(0xe0, buildImuCtrl(0, 0, (magic + 1) & 0xff), (magic + 1) & 0xff, { ackTimeoutMs: 1500 }); } catch {}
try { const sd = buildShutDown(); await session.sendPb(0xe0, sd.pb, sd.magic, { ackTimeoutMs: 1500 }); } catch {}
await session.close();

// ---- report ----
const n = samples.length;
const dur = (t1 - t0) / 1000;
console.log(`\n=== IMU capture: ${n} samples in ${dur.toFixed(2)}s ===`);
if (n >= 2) {
  const rate = n / dur;
  const dts = samples.slice(1).map((s, i) => s.t - samples[i]!.t);
  dts.sort((a, b) => a - b);
  const med = dts[Math.floor(dts.length / 2)]!;
  const rng = (k: "x" | "y" | "z") => { const v = samples.map((s) => s[k]); return { min: Math.min(...v), max: Math.max(...v) }; };
  const rx = rng("x"), ry = rng("y"), rz = rng("z");
  console.log(`delivered rate : ${rate.toFixed(1)} Hz   (median inter-sample ${med.toFixed(1)} ms, min ${dts[0]!.toFixed(1)} ms)`);
  console.log(`requested freq : ${reportFrq}`);
  const fx = (n: number) => n.toFixed(4);
  console.log(`x range        : ${fx(rx.min)} .. ${fx(rx.max)}  (span ${fx(rx.max - rx.min)})`);
  console.log(`y range        : ${fx(ry.min)} .. ${fx(ry.max)}  (span ${fx(ry.max - ry.min)})`);
  console.log(`z range        : ${fx(rz.min)} .. ${fx(rz.max)}  (span ${fx(rz.max - rz.min)})`);
  const mags = samples.map((s) => Math.hypot(s.x, s.y, s.z));
  console.log(`|vector| (mag) : ${fx(Math.min(...mags))} .. ${fx(Math.max(...mags))}  (≈1.0 ⇒ normalized gravity/accel in g)`);
  console.log(`samples (x,y,z):`); for (const s of samples.slice(0, 8)) console.log(`  ${fx(s.x)}, ${fx(s.y)}, ${fx(s.z)}`);
} else {
  console.log("no IMU samples received — the OPEN_IMU request may need EvenHub-mode entry first, or a different Cmd/flag.");
}
process.exit(0);
