#!/usr/bin/env bun
// Vertical scroll on the G2 CFW using ONLY existing display modes — no firmware
// change. A scroll step is one atomic mode-8 message wrapping two sub-messages:
//
//   [8][count=2][len16][mode-9 rect-copy][len16][mode-3 delta]
//
//   * mode 9 shifts the on-device 4bpp shadow by `dy` px (a 2D memmove inside the
//     shadow; costs no airtime — the pixels are already on the glasses).
//   * mode 3 fills ONLY the newly-revealed `dy`-tall strip, sent as zlib'd 4bpp.
//
// mode 8 defers the panel push until after both subs mutate the shadow, so the
// frame is presented once, atomically (no shift-then-fill flicker). So the ONLY
// bytes on the wire per step are the compressed new strip. See the mode 8/9/3
// docs in patches/zlib_glue.c.
//
// Content model: a tall grayscale "page" (W wide, PAGE_H tall). The viewport is a
// WxH window at offset `off` into it. A mode-6 keyframe seeds the shadow with the
// first window; then each step advances `off` by dy and streams just the strip
// that scrolled into view. Swap renderPage() for your own text/image renderer.
//
// Motion: G2_MOTION=momentum (default) runs an inertia/fling auto-demo; keys lets
// you fling by hand (j down / k up / space stop / q quit); pingpong is a constant-
// speed sweep. The POINT of this tool is to judge the FEEL on the real device:
// (1) is the motion smooth, (2) do the two lenses stay in sync, (3) is the present
// rate enough. That gates whether a firmware on-device loop is worth building.
//
//   bun scroll.ts                       # ping-pong scroll a test page
//   G2_DRY_RUN=1 bun scroll.ts          # build messages + report sizes, don't connect
//
// Env:
//   G2_IMG_W / G2_IMG_H   viewport size (default 288x144; max 576x288; W mult of 4, H even)
//   G2_MOTION             momentum (default) | keys | pingpong
//   G2_FLING              fling impulse px/s (default 1600) — momentum/keys
//   G2_FRICTION           velocity decay 1/s (default 2.6) — momentum/keys
//   G2_DEMO_SEC           auto-demo duration s (default 10) — momentum
//   G2_SCROLL_DY          px per step for pingpong (default 8; even)
//   G2_STEPS              pingpong step count (default 240)
//   G2_STEP_MS            pingpong min delay between steps ms (default 0)
//   G2_WINDOW             image messages in flight at once (default 2; 1 = serial)
//   G2_DRY_RUN=1          build/report message sizes only, don't connect

import {
  G2Session,
  buildCreateStartUpPageContainer,
  buildImageContainers,
  buildImageRawData,
  planImageFragments,
  type ImageContainerSpec,
} from "g2-kit/ble";
import { startHeartbeat } from "g2-kit/ui";
import { deflateSync } from "node:zlib";

const ACK_MS = 12_000;
const W = Math.max(16, Math.min(576, Number(process.env.G2_IMG_W ?? "288")));
const H = Math.max(16, Math.min(288, Number(process.env.G2_IMG_H ?? "144")));
const DY = Math.max(2, Number(process.env.G2_SCROLL_DY ?? "8"));
const STEPS = Math.max(1, Number(process.env.G2_STEPS ?? "240"));
const STEP_MS = Math.max(0, Number(process.env.G2_STEP_MS ?? "0"));
const WINDOW = Math.max(1, Number(process.env.G2_WINDOW ?? "2"));
const DRY_RUN = process.env.G2_DRY_RUN === "1";
const ARM = "R";
const MOTION = (process.env.G2_MOTION ?? "momentum").toLowerCase(); // momentum | keys | pingpong
const FLING = Number(process.env.G2_FLING ?? "1600");     // fling impulse, px/s
const FRICTION = Number(process.env.G2_FRICTION ?? "2.6"); // velocity decay, 1/s
const DEMO_SEC = Number(process.env.G2_DEMO_SEC ?? "10");  // momentum auto-demo duration

if (W % 4 !== 0) throw new Error(`G2_IMG_W must be a multiple of 4 (mode-3 quantizes width/4); got ${W}`);
if (H % 2 !== 0 || DY % 2 !== 0) throw new Error(`H and G2_SCROLL_DY must be even (mode-3 quantizes top,height/2); H=${H} dy=${DY}`);
if (DY > H) throw new Error(`dy (${DY}) must be <= viewport height (${H})`);

let magic = 100;
const nextMagic = () => (magic = magic >= 255 ? 100 : magic + 1);

// ---- content: a tall test page (swap this for your text/image renderer) ------
// W-wide, PAGE_H-tall 8bpp grayscale. Numbered bands + a diagonal wash so the
// scroll direction and speed are obvious.
const PAGE_H = H * 6;
function renderPage(): Uint8Array {
  const p = new Uint8Array(W * PAGE_H);
  for (let y = 0; y < PAGE_H; y++) {
    const band = (y >> 4) & 1;                 // 16px horizontal bands
    const tick = y % 32 === 0 ? 255 : 0;       // bright ruler line every 32px
    for (let x = 0; x < W; x++) {
      const wash = ((x + y) >> 2) & 0x0f;      // slow diagonal gradient
      p[y * W + x] = tick || (band ? 40 + wash * 4 : 150 + wash * 4);
    }
  }
  return p;
}
const page = renderPage();

// ---- 4bpp packing (2 px/byte, high nibble = left pixel, value = gray>>4) ------
function pack4bppRegion(x0: number, y0: number, w: number, h: number): Uint8Array {
  const stride = w >> 1;                        // w is even (W mult of 4)
  const out = new Uint8Array(stride * h);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x += 2) {
      const hi = page[(y0 + y) * W + x0 + x]! >> 4;
      const lo = page[(y0 + y) * W + x0 + x + 1]! >> 4;
      out[y * stride + (x >> 1)] = (hi << 4) | lo;
    }
  }
  return out;
}

const putU16 = (a: Uint8Array, o: number, v: number) => { a[o] = v & 0xff; a[o + 1] = (v >> 8) & 0xff; };

// mode 6: headerless tight 4bpp full frame — seeds the shadow. [6][zlib(4bpp WxH)]
function buildKeyframe(offTop: number): Uint8Array {
  const z = deflateSync(pack4bppRegion(0, offTop, W, H));
  const out = new Uint8Array(1 + z.length);
  out[0] = 6;
  out.set(z, 1);
  return out;
}

// mode 9: rect-copy within the shadow. [9] + (sL,sT,sW,sH, dL,dT,dW,dH) u16 LE.
function buildRectCopy(sL: number, sT: number, sW: number, sH: number,
                       dL: number, dT: number, dW: number, dH: number): Uint8Array {
  const out = new Uint8Array(1 + 16);
  out[0] = 9;
  putU16(out, 1, sL); putU16(out, 3, sT); putU16(out, 5, sW); putU16(out, 7, sH);
  putU16(out, 9, dL); putU16(out, 11, dT); putU16(out, 13, dW); putU16(out, 15, dH);
  return out;
}

// mode 3: bounding-box delta (screen box + zlib 4bpp pixels).
// [3][left/4][top/2][width/4][height/2][fidLo][fidHi][zlib]
function buildDelta(left: number, top: number, w: number, h: number, fid: number, px4: Uint8Array): Uint8Array {
  const z = deflateSync(px4);
  const out = new Uint8Array(7 + z.length);
  out[0] = 3;
  out[1] = left >> 2; out[2] = top >> 1; out[3] = w >> 2; out[4] = h >> 1;
  putU16(out, 5, fid);
  out.set(z, 7);
  return out;
}

// mode 8: wrap subs, present once. [8][count][len16 seg]...
function wrapMultes(subs: Uint8Array[]): Uint8Array {
  let n = 2;
  for (const s of subs) n += 2 + s.length;
  const out = new Uint8Array(n);
  out[0] = 8;
  out[1] = subs.length;
  let pos = 2;
  for (const s of subs) { putU16(out, pos, s.length); pos += 2; out.set(s, pos); pos += s.length; }
  return out;
}

// One scroll step. newAtTop=false: content shifts UP, new strip enters at the
// bottom (reading forward). newAtTop=true: content shifts DOWN, new strip at the
// top. `off` is the viewport offset into the page AFTER this step.
function buildScrollStep(off: number, dy: number, newAtTop: boolean, fid: number): Uint8Array {
  const keep = H - dy;
  let rectCopy: Uint8Array, delta: Uint8Array;
  if (newAtTop) {
    rectCopy = buildRectCopy(0, 0, W, keep, 0, dy, W, keep);       // shift down by dy
    delta = buildDelta(0, 0, W, dy, fid, pack4bppRegion(0, off, W, dy)); // fill top strip
  } else {
    rectCopy = buildRectCopy(0, dy, W, keep, 0, 0, W, keep);       // shift up by dy
    delta = buildDelta(0, keep, W, dy, fid, pack4bppRegion(0, off + keep, W, dy)); // fill bottom strip
  }
  return wrapMultes([rectCopy, delta]);
}

// ---- dry run: build every step's message, report wire sizes ------------------
if (DRY_RUN) {
  let off = 0, dirForward = true, fid = 1, total = 0, max = 0;
  for (let i = 0; i < STEPS; i++) {
    if (dirForward && off + DY > PAGE_H - H) dirForward = false;
    else if (!dirForward && off - DY < 0) dirForward = true;
    off += dirForward ? DY : -DY;
    const msg = buildScrollStep(off, DY, !dirForward, fid++);
    total += msg.length; if (msg.length > max) max = msg.length;
  }
  console.log(`[dry-run] ${W}x${H} page ${PAGE_H}px, dy=${DY}, ${STEPS} steps`);
  console.log(`[dry-run] strip/step: avg ${(total / STEPS).toFixed(0)} B, max ${max} B (compressed 4bpp of a ${W}x${DY} strip + 17B rect-copy)`);
  console.log(`[dry-run] keyframe: ${buildKeyframe(0).length} B. Re-run without G2_DRY_RUN=1 to stream.`);
  process.exit(0);
}

// ---- stream --------------------------------------------------------------------
const session = await G2Session.open();
const hb = startHeartbeat({ session, nextMagic });
const suffix = String(Date.now() % 10_000).padStart(4, "0");

// sliding window of in-flight acks (backpressure without a full round trip/step)
let sid = 1;
const inflight: Array<Promise<unknown>> = [];
async function streamPayload(payload: Uint8Array): Promise<boolean> {
  for (const frag of planImageFragments(payload, 4000)) {
    const raw = buildImageRawData({
      containerId: 2, containerName: `c${suffix}`, mapSessionId: sid,
      mapTotalSize: payload.length, mapFragmentIndex: frag.index,
      mapRawData: frag.data, magic: nextMagic(),
    });
    while (inflight.length >= WINDOW) {
      if ((await inflight.shift()) === null) return false;
    }
    const r = await session.sendPbPipelined(0xe0, raw.pb, raw.magic, { ackTimeoutMs: ACK_MS, arm: ARM });
    inflight.push(r.ack);
  }
  sid++;
  return true;
}
async function drain(): Promise<boolean> {
  while (inflight.length) if ((await inflight.shift()) === null) return false;
  return true;
}

try {
  const create = buildCreateStartUpPageContainer({
    name: `b${suffix}`, items: ["."], containerId: 1, captureEvents: false,
    magic: nextMagic(), extraContainerNames: [`c${suffix}`],
  });
  if (!(await session.sendPb(0xe0, create.pb, create.magic, { ackTimeoutMs: ACK_MS }))) throw new Error("CREATE did not ack");
  const container: ImageContainerSpec = {
    name: `c${suffix}`, containerId: 2, x: Math.max(0, (576 - W) >> 1), y: Math.max(0, (288 - H) >> 1), width: W, height: H,
  };
  const rebuild = buildImageContainers({ containers: [container], magic: nextMagic() });
  if (!(await session.sendPb(0xe0, rebuild.pb, rebuild.magic, { ackTimeoutMs: ACK_MS }))) throw new Error("REBUILD did not ack");
  await new Promise((r) => setTimeout(r, 300));   // let the container replicate to ARM

  // seed the shadow with the first window (mode-6 keyframe), fully acked before deltas
  console.log(`[scroll] seeding keyframe (${W}x${H})...`);
  if (!(await streamPayload(buildKeyframe(0))) || !(await drain())) throw new Error("keyframe failed");

  console.log(`[scroll] motion=${MOTION}, window=${WINDOW}, arm=${ARM}. Watch the lens.`);
  const tStart = performance.now();
  const maxPos = (PAGE_H - H) & ~1;                 // even upper bound (mode-3 needs even offsets)
  const evenRound = (x: number) => Math.round(x / 2) * 2;
  let pos = 0, vel = 0, sentPos = 0, fid = 1, sentBytes = 0, sent = 0;
  let dtMin = 1e9, dtMax = 0;

  // Advance the physics by dt and return the mode-8 (or keyframe) payload for the
  // pixels that scrolled into view since the last presented offset, or null if the
  // integer offset didn't move. Even offsets only (mode-3 quantizes top/height /2).
  function stepPayload(dt: number): Uint8Array | null {
    pos += vel * dt;
    vel *= Math.exp(-FRICTION * dt);                // exponential friction (frame-rate independent)
    if (Math.abs(vel) < 4) vel = 0;                 // settle
    pos = Math.max(0, Math.min(maxPos, pos));
    if (pos === 0 || pos === maxPos) vel = 0;       // stop at the ends (no bounce)
    const target = evenRound(pos);
    const dy = target - sentPos;
    if (dy === 0) return null;
    const d = Math.abs(dy);
    sentPos = target;
    // A whole-screen jump (fast fling) is cheaper/cleaner as a keyframe than a strip.
    return d >= H ? buildKeyframe(target) : buildScrollStep(target, d, dy < 0, fid++);
  }

  async function pump(dt: number): Promise<boolean> {
    if (dt > dtMax) dtMax = dt;
    if (dt > 0 && dt < dtMin) dtMin = dt;
    const p = stepPayload(dt);
    if (!p) return true;
    if (!(await streamPayload(p))) return false;
    sentBytes += p.length; sent++;
    return true;
  }

  if (MOTION === "pingpong") {
    let dir = 1;
    for (let i = 0; i < STEPS; i++) {
      if (sentPos + DY > maxPos) dir = -1; else if (sentPos - DY < 0) dir = 1;
      const target = sentPos + dir * DY;
      const msg = buildScrollStep(target, DY, dir < 0, fid++); sentPos = target;
      if (STEP_MS > 0) await new Promise((r) => setTimeout(r, STEP_MS));
      if (!(await streamPayload(msg))) break;
      sentBytes += msg.length; sent++;
    }
  } else if (MOTION === "keys") {
    console.log("  keys: j = fling down   k = fling up   space = stop   q = quit");
    let quit = false, last = performance.now();
    const stdin = process.stdin as unknown as {
      setRawMode?: (b: boolean) => void; resume: () => void;
      setEncoding: (e: string) => void; pause: () => void; on: (e: string, cb: (k: string) => void) => void;
    };
    stdin.setRawMode?.(true); stdin.resume(); stdin.setEncoding("utf8");
    stdin.on("data", (k) => {
      if (k === "j") vel += FLING;
      else if (k === "k") vel -= FLING;
      else if (k === " ") vel = 0;
      else if (k === "q" || k === "") quit = true;
    });
    while (!quit) {
      const now = performance.now(); const dt = Math.min(0.1, (now - last) / 1000); last = now;
      if (!(await pump(dt))) break;
      if (vel === 0) await new Promise((r) => setTimeout(r, 12));
    }
    stdin.setRawMode?.(false); stdin.pause();
  } else {
    // momentum: scripted fling impulses so you can watch inertia + lens-sync hands-off
    const script = [
      { t: 0.3, v: +FLING }, { t: 2.8, v: -FLING },
      { t: 5.0, v: +FLING * 0.6 }, { t: 6.3, v: -FLING * 0.55 }, { t: 7.6, v: +FLING * 0.35 },
    ];
    let si = 0, last = performance.now();
    while ((performance.now() - tStart) / 1000 < DEMO_SEC) {
      const now = performance.now(); const dt = Math.min(0.1, (now - last) / 1000); last = now;
      const el = (now - tStart) / 1000;
      while (si < script.length && script[si]!.t <= el) { vel += script[si]!.v; si++; }
      if (!(await pump(dt))) break;
      if (vel === 0) await new Promise((r) => setTimeout(r, 12));
    }
  }

  await drain();
  const elapsed = (performance.now() - tStart) / 1000;
  console.log(`\n=== motion=${MOTION}: ${sent} steps in ${elapsed.toFixed(1)}s ===`);
  console.log(`  present rate ~${(sent / elapsed).toFixed(1)}/s` +
    (dtMax > 0 ? `  (frame dt ${(dtMin * 1000).toFixed(0)}..${(dtMax * 1000).toFixed(0)} ms)` : ""));
  console.log(`  wire ${(sentBytes / 1024).toFixed(1)} KiB (avg ${(sentBytes / Math.max(1, sent)).toFixed(0)} B/step)`);
  console.log("  judge: (1) 動きが滑らかか  (2) 左右レンズがズレないか  (3) この rate で足りるか");
} finally {
  hb.stop();
  await session.close();
}
process.exit(0);
