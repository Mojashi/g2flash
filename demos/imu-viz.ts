#!/usr/bin/env bun
// imu-viz.ts — live terminal "bubble level" of the G2 head tilt (gravity vector).
// Enables the IMU (via EvenHub mode) and draws a moving dot for head roll/pitch in real
// time (~10 Hz). Run it in your own terminal:  bun imu-viz.ts   (Ctrl-C to stop)
// PLAIN=1 prints plain roll/pitch lines instead of the ANSI grid (for non-TTY checks).
import { G2Session, buildCreateStartUpPageContainer, buildHeartbeat, buildShutDown } from "g2-kit/ble";

// ---- tiny protobuf reader (wire format) ----
function parse(buf: Uint8Array): Map<number, { wt: number; u: number; b: Uint8Array }> {
  const m = new Map<number, { wt: number; u: number; b: Uint8Array }>(); let i = 0;
  while (i < buf.length) {
    let k = 0, s = 0; while (i < buf.length) { const c = buf[i++]!; k |= (c & 0x7f) << s; if (!(c & 0x80)) break; s += 7; }
    const field = k >>> 3, wt = k & 7;
    if (wt === 0) { let v = 0, ss = 0; while (i < buf.length) { const c = buf[i++]!; v += (c & 0x7f) * 2 ** ss; if (!(c & 0x80)) break; ss += 7; } m.set(field, { wt, u: v, b: new Uint8Array() }); }
    else if (wt === 2) { let len = 0, ss = 0; while (i < buf.length) { const c = buf[i++]!; len |= (c & 0x7f) << ss; if (!(c & 0x80)) break; ss += 7; } m.set(field, { wt, u: 0, b: buf.subarray(i, i + len) }); i += len; }
    else if (wt === 5) { m.set(field, { wt, u: (buf[i]! | (buf[i + 1]! << 8) | (buf[i + 2]! << 16) | (buf[i + 3]! << 24)) >>> 0, b: new Uint8Array() }); i += 4; }
    else if (wt === 1) { i += 8; } else break;
  }
  return m;
}
const f32 = (u: number) => new Float32Array(new Uint32Array([u >>> 0]).buffer)[0]!;
function varint(n: number): number[] { const o: number[] = []; let v = n >>> 0; do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; o.push(b); } while (v); return o; }
const vfield = (f: number, v: number) => [...varint((f << 3) | 0), ...varint(v)];
function buildImuCtrl(en: number, freq: number, magic: number): Uint8Array {
  const imu = [...vfield(1, en), ...vfield(2, freq)];
  return new Uint8Array([...vfield(1, 19), ...vfield(2, magic), ...varint((22 << 3) | 2), imu.length, ...imu]);
}
function decodeImu(pb: Uint8Array): { x: number; y: number; z: number } | null {
  for (const cand of [pb, pb.subarray(0, Math.max(0, pb.length - 2))]) {
    try {
      const dev = parse(cand).get(13); if (!dev || dev.wt !== 2) continue;
      const sys = parse(dev.b).get(3); if (!sys || sys.wt !== 2) continue;
      const se = parse(sys.b); const imu = se.get(3);
      if (se.get(1)?.u === 8 && imu && imu.wt === 2) {
        const f = parse(imu.b);
        return { x: f32(f.get(1)?.u ?? 0), y: f32(f.get(2)?.u ?? 0), z: f32(f.get(3)?.u ?? 0) };
      }
    } catch {}
  }
  return null;
}

const PLAIN = process.env.PLAIN === "1";
// The IMU frame vs "level head" mapping isn't known a-priori (mounting-dependent). User
// reported X/Y looked swapped, so default horizontal<-y, vertical<-x. Tune live with env:
//   AXH/AXV = x|y|z (which gravity axis drives horizontal / vertical), INVH/INVV=1 to flip.
const AXH = (process.env.AXH ?? "y") as "x" | "y" | "z";
const AXV = (process.env.AXV ?? "x") as "x" | "y" | "z";
const INVH = process.env.INVH === "1" ? -1 : 1;
const INVV = process.env.INVV === "1" ? -1 : 1;
function tilt(s: { x: number; y: number; z: number }) {
  return {
    h: INVH * Math.atan2(s[AXH], s.z) * 57.2958,   // horizontal tilt (deg)
    v: INVV * Math.atan2(s[AXV], s.z) * 57.2958,   // vertical tilt (deg)
  };
}
let last = { x: 0, y: 0, z: 1 };
let count = 0, t0 = performance.now();

const magic = (Math.floor(Math.random() * 250) + 1) & 0xff;
const session = await G2Session.open({ quiet: true });
session.onRawFrame((frame, _raw, arm) => {
  if (!frame.ok || frame.sid !== 0xe0 || arm !== "R") return;
  const imu = decodeImu(frame.pb);
  if (imu) { last = imu; count++; if (PLAIN) { const r = Math.atan2(imu.x, imu.z) * 57.2958, p = Math.atan2(imu.y, imu.z) * 57.2958; console.log(`roll=${r.toFixed(1)}° pitch=${p.toFixed(1)}°  xyz=(${imu.x.toFixed(2)},${imu.y.toFixed(2)},${imu.z.toFixed(2)})`); } }
});

// enter EvenHub mode + keep alive + open IMU at max rate (~10Hz)
const cre = buildCreateStartUpPageContainer({ name: "imuviz", items: ["IMU"] });
await session.sendPb(0xe0, cre.pb, cre.magic, { ackTimeoutMs: 3000 }).catch(() => {});
const hb = setInterval(() => { const h = buildHeartbeat(); session.sendPb(0xe0, h.pb, h.magic, { ackTimeoutMs: 1500 }).catch(() => {}); }, 3000);
await session.sendPb(0xe0, buildImuCtrl(1, 100, magic), magic, { ackTimeoutMs: 3000 }).catch(() => {});

async function cleanup() {
  clearInterval(hb);
  try { await session.sendPb(0xe0, buildImuCtrl(0, 0, (magic + 1) & 0xff), (magic + 1) & 0xff, { ackTimeoutMs: 1000 }); } catch {}
  try { const sd = buildShutDown(); await session.sendPb(0xe0, sd.pb, sd.magic, { ackTimeoutMs: 1000 }); } catch {}
  try { await session.close(); } catch {}
  process.stdout.write("\x1b[?25h\n");  // show cursor
  process.exit(0);
}
process.on("SIGINT", cleanup);

// ---- render loop ----
const W = 49, H = 19, RANGE = 70;                 // grid + ±degrees mapped to edges
const clamp = (n: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, n));
if (!PLAIN) process.stdout.write("\x1b[2J\x1b[?25l");   // clear + hide cursor
function render() {
  const { x, y, z } = last;
  const roll = Math.atan2(x, z) * 57.2958;        // head side-tilt
  const pitch = Math.atan2(y, z) * 57.2958;       // head up/down
  const mag = Math.hypot(x, y, z);
  const cx = clamp(Math.round(((roll / RANGE) + 1) / 2 * (W - 1)), 0, W - 1);
  const cy = clamp(Math.round((1 - ((pitch / RANGE) + 1) / 2) * (H - 1)), 0, H - 1);
  const rate = count / ((performance.now() - t0) / 1000);
  const midR = (H - 1) >> 1, midC = (W - 1) >> 1;
  let out = "\x1b[H";
  out += `  G2 head-tilt (gravity vector)     ${rate.toFixed(1)} Hz\n`;
  out += "  +" + "-".repeat(W) + "+\n";
  for (let r = 0; r < H; r++) {
    let line = "";
    for (let c = 0; c < W; c++) {
      if (r === cy && c === cx) line += "\x1b[1;92m●\x1b[0m";
      else if (r === midR && c === midC) line += "+";
      else if (r === midR) line += "\x1b[2m-\x1b[0m";
      else if (c === midC) line += "\x1b[2m|\x1b[0m";
      else line += " ";
    }
    out += "  |" + line + "|\n";
  }
  out += "  +" + "-".repeat(W) + "+\n";
  out += `  roll ${roll.toFixed(1).padStart(6)}°   pitch ${pitch.toFixed(1).padStart(6)}°   |v| ${mag.toFixed(3)}   \n`;
  out += `  xyz = (${x.toFixed(3)}, ${y.toFixed(3)}, ${z.toFixed(3)})        \n`;
  out += "  (Ctrl-C to stop)";
  process.stdout.write(out);
}
if (!PLAIN) setInterval(render, 66);   // ~15 fps redraw from the latest sample
