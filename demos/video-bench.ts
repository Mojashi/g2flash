#!/usr/bin/env bun
// Stream a video (GIF) to the lens as fast as it acks, and benchmark byte count
// + framerate. Decodes/rescales/grayscales/compresses ALL frames up front, then
// sends them in order, pacing only on the per-fragment acks.
//
// Each frame is zlib-compressed and sent with a leading mode byte that selects
// a CFW display path. G2_MODE picks the encoding (handy for comparing 4bpp-BMP
// vs 8bpp compressibility and throughput):
//   full  (default) 8bpp: every frame -> mode 2 (full 8bpp frame, raw pixels)
//   delta           8bpp: first frame mode 2, rest mode 3 (XOR delta vs prev)
//   bmp             4bpp: every frame -> mode 1 (full 4bpp indexed BMP)
//   raw4            4bpp: every frame -> mode 6 (headerless 4bpp, fast expander)
// 8bpp carries a full byte per pixel (the panel requantizes to ~16 levels);
// 4bpp is half the raw size before compression. `bmp` (mode 1) runs through the
// stock BMP loader, which decodes with two function calls per pixel; `raw4`
// (mode 6) sends headerless 4bpp and expands it on-device with a plain nibble
// copy, so it gets the 4bpp airtime without the stock decoder's CPU cost.
// Deltas are tiny for content like Bad Apple (mostly-static), so in `delta` mode
// the framerate is dominated by ack latency, not wire bytes; the other three
// send a whole frame every time.
//
//   bun video-bench.ts path/to/bad_apple.gif
//
// Make a GIF from any video with ffmpeg, e.g.:
//   ffmpeg -i bad_apple.mp4 -vf "fps=30,scale=288:144:flags=area,format=gray" bad_apple.gif
//
// Env:
//   G2_IMG_W / G2_IMG_H   target size (default 288x144)
//   G2_IMG_THRESHOLD      >=0 = 1-bit threshold; -1 = grayscale (default -1)
//   G2_MAX_FRAMES         cap frame count (default 0 = all)
//   G2_FRAME_STRIDE       use every Nth decoded frame (default 1)
//   G2_KEYFRAME_INTERVAL  (delta mode) force a full frame every N (default 0 = only the first)
//   G2_MODE               "full" (default), "delta", "bmp", or "raw4" (see above)
//   G2_DRY_RUN=1          decode+compress+report only, don't connect/stream
//   G2_WINDOW             pipelined image messages in flight at once (default 2; 1 = serial)

import {
  G2Session,
  buildCreateStartUpPageContainer,
  buildImageContainers,
  buildImageRawData,
  buildEvenHubBmp,
  planImageFragments,
  type ImageContainerSpec,
} from "g2-kit/ble";
import { startHeartbeat } from "g2-kit/ui";
import { deflateSync } from "node:zlib";
import { GifReader } from "omggif";

const ACK_MS = 12_000;
const W = Math.max(16, Math.min(576, Number(process.env.G2_IMG_W ?? "288")));
const H = Math.max(16, Math.min(288, Number(process.env.G2_IMG_H ?? "144")));
const THRESHOLD = Math.max(-1, Math.min(255, Number(process.env.G2_IMG_THRESHOLD ?? "-1")));
const MAX_FRAMES = Math.max(0, Number(process.env.G2_MAX_FRAMES ?? "0"));
const STRIDE = Math.max(1, Number(process.env.G2_FRAME_STRIDE ?? "1"));
const KEYFRAME_INTERVAL = Math.max(0, Number(process.env.G2_KEYFRAME_INTERVAL ?? "0"));
const MODE = (process.env.G2_MODE ?? "full").toLowerCase(); // "full" | "delta" | "bmp" | "raw4"
if (!["full", "delta", "bmp", "raw4"].includes(MODE)) {
  console.error(`G2_MODE must be one of full|delta|bmp|raw4 (got "${MODE}")`);
  process.exit(1);
}
const BMP4 = MODE === "bmp";    // mode 1: full 4bpp BMP per frame (stock BMP path)
const RAW4 = MODE === "raw4";   // mode 6: headerless 4bpp, our fast expander
const DELTA = MODE === "delta"; // mode 2 keyframes + mode 3 XOR deltas
const DRY_RUN = process.env.G2_DRY_RUN === "1";
const WINDOW = Math.max(1, Number(process.env.G2_WINDOW ?? "2"));
const IMAGE_SEND_ARM = "R";

let magic = 100;
const nextMagic = () => (magic = magic >= 255 ? 100 : magic + 1);

const videoPath = process.argv[2] ?? process.env.G2_VIDEO;
if (!videoPath) {
  console.error("usage: bun video-bench.ts <video.gif>  (see header for ffmpeg one-liner)");
  process.exit(1);
}

// ---- decode GIF -> grayscale frames at WxH (nearest-neighbor rescale) ----
const gifBuf = new Uint8Array(await Bun.file(videoPath).arrayBuffer());
const gif = new GifReader(gifBuf);
const W0 = gif.width, H0 = gif.height;
const total = gif.numFrames();
console.log(`[decode] ${videoPath}: ${W0}x${H0}, ${total} frames -> target ${W}x${H}`);

function rescaleGray(rgba: Uint8Array): Uint8Array {
  const out = new Uint8Array(W * H);
  if (THRESHOLD >= 0) {
    for (let y = 0; y < H; y++) {
      const sy = Math.min(H0 - 1, ((y * H0) / H) | 0);
      for (let x = 0; x < W; x++) {
        const sx = Math.min(W0 - 1, ((x * W0) / W) | 0);
        const i = (sy * W0 + sx) * 4;
        out[y * W + x] = (rgba[i]! > THRESHOLD ? 255 : 0);
      }
    }
    return out;
  } else {
    for (let y = 0; y < H; y++) {
      const sy = Math.min(H0 - 1, ((y * H0) / H) | 0);
      for (let x = 0; x < W; x++) {
        const sx = Math.min(W0 - 1, ((x * W0) / W) | 0);
        const i = (sy * W0 + sx) * 4;
        out[y * W + x] = (rgba[i]! * 0.299 + rgba[i + 1]! * 0.587 + rgba[i + 2]! * 0.114) | 0;
      }
    }
    return out;
  }
}

// ---- build per-frame payloads up front ([mode][zlib]) ----
type FrameStat = { bytes: number; key: boolean };
const payloads: Uint8Array[] = [];
const stats: FrameStat[] = [];
const rgba = new Uint8Array(W0 * H0 * 4);
let dispose: { x: number; y: number; w: number; h: number } | null = null;
let prev: Uint8Array | null = null;
let used = 0;

const t0 = performance.now();
for (let i = 0; i < total; i++) {
  if (dispose) {
    for (let yy = dispose.y; yy < dispose.y + dispose.h; yy++)
      rgba.fill(0, (yy * W0 + dispose.x) * 4, (yy * W0 + dispose.x + dispose.w) * 4);
  }
  const fi = gif.frameInfo(i);
  gif.decodeAndBlitFrameRGBA(i, rgba);
  dispose = fi.disposal === 2 ? { x: fi.x, y: fi.y, w: fi.width, h: fi.height } : null;

  if (i % STRIDE !== 0) continue;
  const gray = rescaleGray(rgba);
  // In delta mode a frame is a keyframe on the first frame or every Nth; full
  // and bmp modes send a whole frame every time.
  const isKey = !DELTA || prev === null || (KEYFRAME_INTERVAL > 0 && used % KEYFRAME_INTERVAL === 0);
  let payload: Uint8Array;
  if (BMP4) {
    // mode 1: full 4bpp indexed BMP (gray 0..255 -> 0..15), zlib-compressed.
    const bmp = buildEvenHubBmp(W, H, (x, y) => gray[y * W + x]! >> 4);
    payload = pack(1, bmp);
  } else if (RAW4) {
    // mode 6: headerless tight 4bpp (gray>>4), our fast on-device expander.
    payload = pack(6, pack4bpp(gray));
  } else if (isKey) {
    payload = pack(2, gray);
  } else {
    const d = new Uint8Array(W * H);
    for (let k = 0; k < d.length; k++) d[k] = gray[k]! ^ prev![k]!;
    payload = pack(3, d);
  }
  payloads.push(payload);
  stats.push({ bytes: payload.length, key: isKey });
  prev = gray;
  used++;
  if (MAX_FRAMES && used >= MAX_FRAMES) break;
  if (used % 200 === 0) console.log(`[decode] ${used} frames prepared...`);
}
const prepMs = performance.now() - t0;

const keyBytes = stats.filter((s) => s.key).reduce((a, s) => a + s.bytes, 0);
const keyN = stats.filter((s) => s.key).length;
const deltaBytes = stats.filter((s) => !s.key).reduce((a, s) => a + s.bytes, 0);
const deltaN = stats.length - keyN;
const totalBytes = keyBytes + deltaBytes;
console.log(
  `[prepared] mode=${MODE} ${W}x${H} ${payloads.length} frames in ${(prepMs / 1000).toFixed(1)}s | ` +
    `${(totalBytes / 1024).toFixed(0)} KiB total, avg ${(totalBytes / payloads.length).toFixed(0)} B/frame ` +
    `(keyframes ${keyN}@${keyN ? (keyBytes / keyN).toFixed(0) : 0}B, deltas ${deltaN}@${deltaN ? (deltaBytes / deltaN).toFixed(0) : 0}B)`,
);

function pack(mode: number, raw: Uint8Array): Uint8Array {
  const z = deflateSync(raw);
  const out = new Uint8Array(z.length + 1);
  out[0] = mode;
  out.set(z, 1);
  return out;
}

// Tightly-packed 4bpp (mode 6): gray 0..255 -> nibble (gray>>4), 2 px/byte with
// the left pixel in the high nibble, rows top-down, stride = ceil(W/2), no
// padding. Matches the firmware's headerless-4bpp expander.
function pack4bpp(gray: Uint8Array): Uint8Array {
  const stride = (W + 1) >> 1;
  const out = new Uint8Array(stride * H);
  for (let y = 0; y < H; y++) {
    for (let x = 0; x < W; x += 2) {
      const hi = gray[y * W + x]! >> 4;
      const lo = x + 1 < W ? gray[y * W + x + 1]! >> 4 : 0;
      out[y * stride + (x >> 1)] = (hi << 4) | lo;
    }
  }
  return out;
}

if (DRY_RUN) {
  console.log("[dry-run] not sending. (re-run without G2_DRY_RUN=1 to stream to the device)");
  process.exit(0);
}

const session = await G2Session.open();
const hb = startHeartbeat({ session, nextMagic });
const suffix = String(Date.now() % 10_000).padStart(4, "0");

try {
  const create = buildCreateStartUpPageContainer({
    name: `b${suffix}`, items: ["."], containerId: 1, captureEvents: false, magic: nextMagic(), extraContainerNames: [`c${suffix}`],
  });
  if (!(await session.sendPb(0xe0, create.pb, create.magic, { ackTimeoutMs: ACK_MS }))) throw new Error("CREATE did not ack");
  const container: ImageContainerSpec = {
    name: `c${suffix}`, containerId: 2, x: Math.max(0, (576 - W) >> 1), y: Math.max(0, (288 - H) >> 1), width: W, height: H,
  };
  const rebuild = buildImageContainers({ containers: [container], magic: nextMagic() });
  if (!(await session.sendPb(0xe0, rebuild.pb, rebuild.magic, { ackTimeoutMs: ACK_MS }))) throw new Error("REBUILD did not ack");
  // Layout is created on the default arm; we stream to IMAGE_SEND_ARM. Let the
  // container replicate to that lens before the first frame to avoid a race.
  await new Promise((r) => setTimeout(r, 300));

  console.log(`[stream] sending ${payloads.length} frames, mode=${MODE}, window=${WINDOW}, arm=${IMAGE_SEND_ARM}...`);
  let sid = 1, sent = 0, sentBytes = 0, aborted = false;
  let latSum = 0, latN = 0, latWorst = 0;
  const lats: number[] = [];

  // Sliding window of in-flight acks: each image-raw message fires immediately
  // (only its BLE write is awaited); we await the oldest ack before exceeding
  // WINDOW outstanding, so the firmware sees backpressure but we don't pay a
  // full ack round trip per message.
  const inflight: Array<{ ack: Promise<unknown>; t: number }> = [];
  const awaitOldest = async (): Promise<boolean> => {
    const it = inflight.shift()!;
    const ack = await it.ack;
    const lat = performance.now() - it.t;
    latSum += lat; latN++; if (lat > latWorst) latWorst = lat;
    lats.push(lat);
    return ack !== null;
  };
  const sendMsg = async (pb: Uint8Array, mg: number): Promise<boolean> => {
    while (inflight.length >= WINDOW) {
      if (!(await awaitOldest())) return false;
    }
    const r = await session.sendPbPipelined(0xe0, pb, mg, { ackTimeoutMs: ACK_MS, arm: IMAGE_SEND_ARM });
    inflight.push({ ack: r.ack, t: performance.now() });
    return true;
  };

  const tStart = performance.now();
  for (let i = 0; i < payloads.length; i++) {
    for (const frag of planImageFragments(payloads[i]!, 4000)) {
      const raw = buildImageRawData({
        containerId: container.containerId, containerName: container.name, mapSessionId: sid,
        mapTotalSize: payloads[i]!.length, mapFragmentIndex: frag.index,
        mapRawData: frag.data, magic: nextMagic(), // packet size is derived from mapRawData.length
      });
      if (!(await sendMsg(raw.pb, raw.magic))) { aborted = true; break; }
    }
    sid++;
    if (aborted) { console.log(`[stream] frame ${i} NO_ACK — aborting`); break; }
    sent++;
    sentBytes += payloads[i]!.length;
    if (sent % 100 === 0) {
      const fps = sent / ((performance.now() - tStart) / 1000);
      console.log(`[stream] ${sent}/${payloads.length}  ${fps.toFixed(1)} fps  ${(sentBytes / 1024).toFixed(0)} KiB`);
    }
  }
  // drain the rest of the window so elapsed covers every ack
  while (!aborted && inflight.length) {
    if (!(await awaitOldest())) aborted = true;
  }

  const elapsed = (performance.now() - tStart) / 1000;
  const fps = sent / elapsed;
  // Percentiles over all observed ack latencies (nearest-rank on the sorted set).
  const sortedLats = [...lats].sort((a, b) => a - b);
  const pct = (p: number) =>
    sortedLats.length ? sortedLats[Math.min(sortedLats.length - 1, Math.ceil(p * sortedLats.length) - 1)]! : 0;
  const p90 = pct(0.9), p99 = pct(0.99);
  // A worst >1000 ms almost certainly means the run ended on a timeout/disconnect,
  // so the "worst" is that terminal stall, not a representative ack — surface the
  // next-worst latency too so the tail is still readable.
  const secondWorst = sortedLats.length >= 2 ? sortedLats[sortedLats.length - 2]! : 0;
  const showSecond = latWorst > 1000 && sortedLats.length >= 2;
  console.log(
    `\n=== RESULT (mode=${MODE}, ${W}x${H}, window=${WINDOW}) ===\n` +
      `frames sent : ${sent}${aborted ? " (aborted early)" : ""}\n` +
      `elapsed     : ${elapsed.toFixed(1)} s\n` +
      `framerate   : ${fps.toFixed(2)} fps  (${(1000 / fps).toFixed(0)} ms/frame)\n` +
      `ack latency : avg ${latN ? (latSum / latN).toFixed(0) : 0} ms, p90 ${p90.toFixed(0)} ms, p99 ${p99.toFixed(0)} ms, worst ${latWorst.toFixed(0)} ms` +
      `${showSecond ? ` (2nd-worst ${secondWorst.toFixed(0)} ms)` : ""}  (round trip pipelining hides)\n` +
      `wire image  : ${(sentBytes / 1024).toFixed(0)} KiB  (avg ${sent ? (sentBytes / sent).toFixed(0) : 0} B/frame, ${((sentBytes * 8) / elapsed / 1000).toFixed(0)} kbit/s)\n` +
      `(image bytes only; protobuf+aa21 envelope add per-fragment overhead)`,
  );
} finally {
  hb.stop();
  await session.close();
}
process.exit(0);
