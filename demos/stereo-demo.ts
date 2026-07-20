#!/usr/bin/env bun
// Stereoscopic 3D demo for the Even G2 — shows off the custom firmware's
// PER-LENS STEREO PAIR path (image mode 4). Renders a left-eye and a right-eye
// view of an animated 3D scene with correct binocular disparity, packs the two
// grayscale frames into one message, and streams it. The CFW splits the pair so
// the LEFT lens draws the left-eye half and the RIGHT lens the right-eye half —
// each eye gets a slightly different image and the brain fuses them into depth.
//
//   bun stereo-demo.ts                 # rotating wireframe cube (default)
//   G2_SCENE=rings bun stereo-demo.ts  # flying through a tunnel of rings
//   G2_SCENE=rds   bun stereo-demo.ts  # random-dot stereogram (pure stereopsis)
//
// No glasses handy? Render a preview instead of streaming:
//   G2_DRY_RUN=1 bun stereo-demo.ts    # writes stereo-preview-*.bmp (side-by-
//                                      # side + red/cyan anaglyph) you can open
//
// How the stereo works (the interesting bit):
//   Two virtual cameras sit a small interocular distance (IOD) apart on X, both
//   looking down +Z. A world point P=(X,Y,Z) projects to
//       u_L = cx + f*(X + IOD/2)/Z - f*IOD/(2*Zc)
//       u_R = cx + f*(X - IOD/2)/Z + f*IOD/(2*Zc)
//       v   = cy - f*Y/Z            (no vertical disparity)
//   The last term converges both eyes on depth Zc (zero disparity there). The
//   left-minus-right disparity is  f*IOD*(1/Z - 1/Zc): points NEARER than Zc get
//   crossed disparity (u_L>u_R) and pop OUT of the display; points farther get
//   uncrossed disparity and sit BEHIND it. Keep the magnitude small (a handful of
//   px) or the eyes can't fuse — tune with the env vars below.
//
// Wire format per frame (CFW image mode 4):
//   [0x04][ zlib( leftEye[W*H] ++ rightEye[W*H] ) ]     (8bpp, 1 byte/pixel)
// sent as ~4 KB fragments to ONE arm; the firmware's cross-lens completion sync
// runs the decoder on both lenses and each keeps only its half (FW_SIDE).
//
// Env:
//   G2_SCENE        cube (default) | rings | rds
//   G2_IMG_W/H      lens image size (default 288x144; CFW max 576x288)
//   G2_FRAMES       number of frames to render/stream (default 600)
//   G2_FPS          target pacing when streaming (default 0 = as fast as acks)
//   G2_IOD          interocular distance, world units (default 0.4)
//   G2_FOCAL        focal length in px (default 210)
//   G2_CONVERGE     convergence depth Zc (default 5.5) — zero-disparity plane
//   G2_WINDOW       image messages in flight at once (default 2)
//   G2_DRY_RUN=1    render a preview BMP, don't connect
//   G2_PREVIEW_FRAME which frame index the preview captures (default 30)

import {
  G2Session,
  buildCreateStartUpPageContainer,
  buildImageContainers,
  buildImageRawData,
  buildShutDown,
  planImageFragments,
  queryCapabilities,
  hasFeature,
  type ImageContainerSpec,
} from "g2-kit/ble";
import { startHeartbeat } from "g2-kit/ui";
import { deflateSync } from "node:zlib";
import { readFileSync } from "node:fs";

// ---------------------------------------------------------------- config -----
const clampI = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v | 0));
const W = clampI(Number(process.env.G2_IMG_W ?? "288"), 16, 576);
const H = clampI(Number(process.env.G2_IMG_H ?? "144"), 16, 288);
const SCENE = (process.env.G2_SCENE ?? "cube").toLowerCase();
const FRAMES = clampI(Number(process.env.G2_FRAMES ?? "600"), 1, 100_000);
const FPS = Math.max(0, Number(process.env.G2_FPS ?? "0"));
const IOD = Number(process.env.G2_IOD ?? "0.4");
const FOCAL = Number(process.env.G2_FOCAL ?? "210");
const ZC = Number(process.env.G2_CONVERGE ?? "5.5");
const WINDOW = clampI(Number(process.env.G2_WINDOW ?? "2"), 1, 8);
const DRY_RUN = process.env.G2_DRY_RUN === "1";
const PREVIEW_FRAME = clampI(Number(process.env.G2_PREVIEW_FRAME ?? "30"), 0, FRAMES - 1);
const ACK_MS = 12_000;
const IMAGE_SEND_ARM = "R" as const;

if (!["cube", "rings", "rds", "map"].includes(SCENE)) {
  console.error(`G2_SCENE must be one of cube|rings|rds|map (got "${SCENE}")`);
  process.exit(1);
}

const CX = W / 2, CY = H / 2;
const CONV_SHIFT = (FOCAL * IOD) / (2 * ZC); // per-eye horizontal convergence offset (px)

// Safety cap on a SINGLE container's size. The img576 CFW patch lifts the
// container-dimension *check* to 576x288, but it only rewrites the width/height
// upper-bound comparison — it does NOT enlarge the per-container display buffer
// allocation. So a single container larger than the stock 288x144 max very likely
// overflows that buffer when a full 8bpp frame is written, which crashed + rebooted
// the glasses at 576x288 here. (The kit's own docs say full-panel content is meant
// to be tiled as a 2x2 grid of 288x144 containers, and the firmware even keys its
// snapshot FIFO for "4 tiles" — i.e. tiling, not one big container, is the intended
// path.) Refuse a single container above the stock max unless explicitly forced, so
// a stray G2_IMG_W/H can't reboot a live session.
// Tiling: split the full frame into a grid of sub-containers, each <= the stock
// 288x144 max, and send each tile its own mode-4 stereo message. This is how the
// full 576x288 panel is covered safely — a single container above 288x144
// overflows the per-container display buffer and reboots the glasses (see the
// img576 note). G2_TILED=1 turns it on; the grid is chosen so every tile fits.
const TILED = process.env.G2_TILED === "1";
const HOLD = process.env.G2_HOLD === "1";   // after streaming, keep re-sending the last frame (no shutdown) so a still image persists
const TILE_COLS = TILED ? Math.max(1, Math.round(W / 288)) : 1;
const TILE_ROWS = TILED ? Math.max(1, Math.round(H / 144)) : 1;
const TILE_W = Math.floor(W / TILE_COLS);
const TILE_H = Math.floor(H / TILE_ROWS);
if (TILE_W * TILE_COLS !== W || TILE_H * TILE_ROWS !== H) {
  console.error(`tiling: ${W}x${H} must divide evenly into ${TILE_COLS}x${TILE_ROWS} tiles`);
  process.exit(1);
}

const STOCK_MAX_PX = 288 * 144;      // 41472 — the pre-CFW single-container ceiling
const FORCE_BIG = process.env.G2_FORCE_BIG === "1";
if (!DRY_RUN && TILE_W * TILE_H > STOCK_MAX_PX && !FORCE_BIG) {
  console.error(
    `refusing ${TILE_W}x${TILE_H} per container (${TILE_W * TILE_H} > ${STOCK_MAX_PX} px): ` +
    `above 288x144 a single container overflows the CFW display buffer and reboots the ` +
    `glasses. For the full panel set G2_TILED=1 (2x2 tiles of 288x144), keep to 288x144, ` +
    `or set G2_FORCE_BIG=1 to override at your own risk.`);
  process.exit(1);
}

// ------------------------------------------------------------- 3D scenes -----
// Each scene, for a given normalized time t in [0,1), yields either a set of 3D
// line segments (cube/rings — drawn as glowing wireframe, ideal for the
// see-through display) or is handled specially (rds). Coordinates are world
// units with the camera at the origin looking toward +Z; visible points have Z>0.

type V3 = { x: number; y: number; z: number };
type Seg = { a: V3; b: V3; i?: number }; // i = brightness 0..1 (default 1), for depth fade

function rotY(p: V3, a: number): V3 {
  const c = Math.cos(a), s = Math.sin(a);
  return { x: c * p.x + s * p.z, y: p.y, z: -s * p.x + c * p.z };
}
function rotX(p: V3, a: number): V3 {
  const c = Math.cos(a), s = Math.sin(a);
  return { x: p.x, y: c * p.y - s * p.z, z: s * p.y + c * p.z };
}
function add(p: V3, q: V3): V3 { return { x: p.x + q.x, y: p.y + q.y, z: p.z + q.z }; }

// --- scene: a wireframe cube rotating about two axes, centered on the
// convergence plane so it swings between popping out and receding.
const CUBE_VERTS: V3[] = [];
for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1])
  CUBE_VERTS.push({ x: sx, y: sy, z: sz });
const CUBE_EDGES: [number, number][] = [];
for (let i = 0; i < 8; i++) for (let j = i + 1; j < 8; j++) {
  // two cube vertices share an edge iff they differ in exactly one coordinate
  const d = (CUBE_VERTS[i]!.x !== CUBE_VERTS[j]!.x ? 1 : 0) +
            (CUBE_VERTS[i]!.y !== CUBE_VERTS[j]!.y ? 1 : 0) +
            (CUBE_VERTS[i]!.z !== CUBE_VERTS[j]!.z ? 1 : 0);
  if (d === 1) CUBE_EDGES.push([i, j]);
}

function cubeScene(t: number): Seg[] {
  const ay = t * Math.PI * 2, ax = t * Math.PI * 2 * 0.61 + 0.4;
  const half = 1.25;                              // cube half-side (world units)
  const center: V3 = { x: 0, y: 0, z: ZC };       // sits on the zero-disparity plane
  const pts = CUBE_VERTS.map((v) =>
    add(center, rotX(rotY({ x: v.x * half, y: v.y * half, z: v.z * half }, ay), ax)));
  return CUBE_EDGES.map(([i, j]) => ({ a: pts[i]!, b: pts[j]! }));
}

// --- scene: a receding tunnel of rings — a strong, unmistakable depth gradient.
// Rings fly toward the camera and recycle to the back. Depth range is bounded so
// disparity stays fusible (~±8 px), and rings fade in/out at the near/far ends so
// the recycle is a smooth dissolve rather than a pop.
const RING_COUNT = 10;
const RING_SEGS = 40;
const RING_SPACING = 0.7;
const RING_NEAR = 3.4;   // cull nearer than this (would exceed comfortable disparity)
const RING_BASE = 3.6;   // frontmost ring's home depth
function ringsScene(t: number): Seg[] {
  const segs: Seg[] = [];
  const flow = (t * RING_COUNT * RING_SPACING) % RING_SPACING; // continuous forward drift
  const zFar = RING_BASE + (RING_COUNT - 1) * RING_SPACING;
  for (let r = 0; r < RING_COUNT; r++) {
    const z = RING_BASE + r * RING_SPACING - flow;
    if (z < RING_NEAR) continue;
    // fade in over the first 0.9 units of visibility, fade out over the last 1.2
    const fade = Math.min(1, (z - RING_NEAR) / 0.9) * Math.min(1, (zFar - z + 0.4) / 1.2);
    const radius = 1.7 + 0.4 * Math.sin(t * Math.PI * 2 + r * 0.5); // gentle breathing
    const spin = t * Math.PI * 2 * 0.25 + r * 0.15;
    const ptOf = (k: number): V3 => {
      const a = (k / RING_SEGS) * Math.PI * 2 + spin;
      return { x: Math.cos(a) * radius, y: Math.sin(a) * radius, z };
    };
    for (let k = 0; k < RING_SEGS; k++) segs.push({ a: ptOf(k), b: ptOf(k + 1), i: Math.max(0, fade) });
  }
  return segs;
}

// --- scene: a stylized 3D city viewed from a slowly orbiting, tilted-down
// camera — a stand-in for the "look around a 3D map" app. Ground grid + boxy
// buildings of varying height, all wireframe (bright thin lines on black read
// well on the see-through panel). Buildings span a real depth range so the near
// blocks pop out and the far skyline recedes. Deterministic layout (seeded PRNG)
// so a given frame renders identically every run.
function mulberry32(seed: number): () => number {
  let s = seed | 0;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
const MAP_DIST = Number(process.env.G2_MAP_DIST ?? "11");     // camera distance to city centre
const MAP_ELEV = Number(process.env.G2_MAP_ELEV ?? "-0.52");  // camera tilt (rad): look down
const MAP_TARGET_Y = Number(process.env.G2_MAP_TARGET_Y ?? "0.7"); // vertical framing
const MAP_SPAN = Number(process.env.G2_MAP_SPAN ?? "4.6");    // world half-extent the city fills

// Real building data (OpenStreetMap via fetch-city.ts), loaded once if present.
// Each building: { h: metres, poly: [[x,z]...] metres, centred on the bbox }. If
// city.json is missing, mapScene falls back to a procedural block city.
type CityData = { extent_m: number; source?: string; buildings: { h: number; poly: [number, number][] }[] };
let CITY: CityData | null = null;
try {
  CITY = JSON.parse(readFileSync(process.env.G2_CITY ?? "city.json", "utf8")) as CityData;
  if (!CITY.buildings?.length) CITY = null;
} catch { CITY = null; }

// world point -> camera space (camera at origin looking +Z): recentre on the
// target, spin by the orbit azimuth (Y), tilt down (X), push out by MAP_DIST.
function orbit(azimuth: number): (p: V3) => V3 {
  return (p: V3): V3 => {
    let q: V3 = { x: p.x, y: p.y - MAP_TARGET_Y, z: p.z };
    q = rotY(q, azimuth);
    q = rotX(q, MAP_ELEV);
    q.z += MAP_DIST;
    return q;
  };
}
function groundGrid(toCam: (p: V3) => V3, half: number, step: number, segs: Seg[]) {
  for (let g = -half; g <= half + 1e-6; g += step) {
    segs.push({ a: toCam({ x: -half, y: 0, z: g }), b: toCam({ x: half, y: 0, z: g }), i: 0.26 });
    segs.push({ a: toCam({ x: g, y: 0, z: -half }), b: toCam({ x: g, y: 0, z: half }), i: 0.26 });
  }
}

// G2_MAP_AZ pins the orbit to a fixed azimuth (radians) => a STILL frame, which
// is the only way tiling gives clean stereo: with a moving scene the left lens
// (rendered via the cross-lens sync, a beat behind the right) shows a different
// moment than the right, so the SAME tile fuses badly. A still frame lets both
// lenses converge on the identical image. G2_ORBIT_TURNS sets the animated speed.
const MAP_AZ = process.env.G2_MAP_AZ;
const ORBIT_TURNS = Number(process.env.G2_ORBIT_TURNS ?? "1");
function mapScene(t: number): Seg[] {
  const segs: Seg[] = [];
  const azimuth = MAP_AZ !== undefined ? Number(MAP_AZ) : t * Math.PI * 2 * ORBIT_TURNS;
  const toCam = orbit(azimuth);
  groundGrid(toCam, MAP_SPAN * 1.05, MAP_SPAN / 5, segs);

  if (CITY) {
    // Real OSM footprints extruded to their height: bright roof outline + mid
    // verticals (verticals already meet the ground, so the base outline is dropped
    // to keep the payload light — heavy frames overwhelm the firmware's ack path).
    // Cap the building count (tallest first, already sorted) for the same reason.
    const s = MAP_SPAN / Math.max(1, CITY.extent_m);
    const maxB = Number(process.env.G2_MAX_BLDG ?? "28");
    for (const b of CITY.buildings.slice(0, maxB)) {
      const h = b.h * s;
      const base: V3[] = b.poly.map(([x, z]) => ({ x: x * s, y: 0, z: z * s }));
      const n = base.length;
      for (let k = 0; k < n; k++) {
        const kn = (k + 1) % n;
        const t0 = { x: base[k]!.x, y: h, z: base[k]!.z };
        const t1 = { x: base[kn]!.x, y: h, z: base[kn]!.z };
        segs.push({ a: toCam(t0), b: toCam(t1), i: 1 });          // roof outline
        segs.push({ a: toCam(base[k]!), b: toCam(t0), i: 0.72 }); // vertical edge
      }
    }
    return segs;
  }

  // Fallback: procedural block city (seeded, deterministic).
  const rnd = mulberry32(20260717);
  const N = 6, spacing = 1.55;
  for (let gx = 0; gx < N; gx++) for (let gz = 0; gz < N; gz++) {
    if (rnd() < 0.16) continue;
    const cx = (gx - (N - 1) / 2) * spacing, cz = (gz - (N - 1) / 2) * spacing;
    const h = 0.4 + rnd() * rnd() * 2.7;
    const w = spacing * (0.42 + rnd() * 0.18), d = spacing * (0.42 + rnd() * 0.18);
    const base: V3[] = [{ x: cx - w, y: 0, z: cz - d }, { x: cx + w, y: 0, z: cz - d }, { x: cx + w, y: 0, z: cz + d }, { x: cx - w, y: 0, z: cz + d }];
    const top: V3[] = base.map((p) => ({ x: p.x, y: h, z: p.z }));
    for (let k = 0; k < 4; k++) segs.push({ a: toCam(base[k]!), b: toCam(top[k]!), i: 0.75 });
    for (let k = 0; k < 4; k++) segs.push({ a: toCam(top[k]!), b: toCam(top[(k + 1) % 4]!), i: 1 });
  }
  return segs;
}

// Overlay the 2x2 tile seams (at W/2 and H/2) as faint lines, to visualize how a
// full-panel frame is transported as four 288x144 stereo tiles. Same in both eyes
// (screen-depth), so it just marks the physical tile boundaries.
function overlayTileGrid(buf: Uint8Array) {
  const v = 70;
  for (let y = 0; y < H; y++) { const i = y * W + (W >> 1); if (v > buf[i]!) buf[i] = v; }
  for (let x = 0; x < W; x++) { const i = (H >> 1) * W + x; if (v > buf[i]!) buf[i] = v; }
}

// ------------------------------------------------- projection + raster --------
// Project a world point to one eye's screen. eyeSign: -1 = left eye, +1 = right.
function project(p: V3, eyeSign: number): { u: number; v: number; z: number } {
  const z = p.z;
  const u = CX + (FOCAL * (p.x - eyeSign * (IOD / 2))) / z - eyeSign * CONV_SHIFT;
  const v = CY - (FOCAL * p.y) / z;
  return { u, v, z };
}

// Line rasterizer into an 8bpp buffer, max-compositing so crossing lines stay a
// clean single brightness. Anti-aliasing (Xiaolin Wu) looks smoother but is a
// COMPRESSION DISASTER for this pipeline: every edge becomes a continuous gray
// ramp, so the frame is full of distinct byte values and zlib can't find runs.
// With G2_AA=0 (recommended for dense scenes) lines are hard 1-value pixels, so
// the frame is long runs of 0x00 plus a few line values -> compresses many times
// smaller (fewer BLE fragments = faster + more reliable on-device).
const AA = process.env.G2_AA !== "0";
function plot(buf: Uint8Array, x: number, y: number, a: number) {
  if (x < 0 || x >= W || y < 0 || y >= H || a <= 0) return;
  const i = y * W + x;
  const v = a > 1 ? 255 : (a * 255) | 0;
  if (v > buf[i]!) buf[i] = v;
}
function drawLine(buf: Uint8Array, x0: number, y0: number, x1: number, y1: number, gain = 1) {
  const steep = Math.abs(y1 - y0) > Math.abs(x1 - x0);
  if (steep) { [x0, y0] = [y0, x0]; [x1, y1] = [y1, x1]; }
  if (x0 > x1) { [x0, x1] = [x1, x0]; [y0, y1] = [y1, y0]; }
  const dx = x1 - x0, dy = y1 - y0;
  const grad = dx === 0 ? 1 : dy / dx;
  let inter = y0 + grad * (Math.round(x0) - x0) + grad;
  const put = (px: number, py: number, a: number) =>
    steep ? plot(buf, py, px, a * gain) : plot(buf, px, py, a * gain);
  const xEnd0 = Math.round(x0), xEnd1 = Math.round(x1);
  put(xEnd0, Math.round(y0), 1);
  put(xEnd1, Math.round(y1), 1);
  for (let x = xEnd0 + 1; x < xEnd1; x++) {
    if (AA) {
      const fpart = inter - Math.floor(inter);
      put(x, Math.floor(inter), 1 - fpart);
      put(x, Math.floor(inter) + 1, fpart);
    } else {
      put(x, Math.round(inter), 1);   // single hard pixel, one value -> compresses
    }
    inter += grad;
  }
}

// Render one eye of a wireframe scene. Clips segments to Z>near before projecting.
function renderWire(segs: Seg[], eyeSign: number): Uint8Array {
  const buf = new Uint8Array(W * H);
  const NEAR = 0.6;
  for (const s of segs) {
    if (s.a.z <= NEAR && s.b.z <= NEAR) continue; // fully behind the near plane
    let a = s.a, b = s.b;
    if (a.z <= NEAR || b.z <= NEAR) {              // clip the segment to z=NEAR
      const [inP, outP] = a.z > NEAR ? [a, b] : [b, a];
      const tt = (inP.z - NEAR) / (inP.z - outP.z);
      const clipped: V3 = {
        x: inP.x + (outP.x - inP.x) * tt,
        y: inP.y + (outP.y - inP.y) * tt,
        z: NEAR + 1e-4,
      };
      a = inP; b = clipped;
    }
    const pa = project(a, eyeSign), pb = project(b, eyeSign);
    drawLine(buf, pa.u, pa.v, pb.u, pb.v, s.i ?? 1);
  }
  return buf;
}

// --- scene: random-dot stereogram. Pure stereopsis — neither eye alone shows
// anything but noise; only fused do the dots resolve into a floating shape.
// A soft-edged blob at an oscillating depth floats above a flat dot field.
// Deterministic PRNG so a frame renders identically on every run (and left/right
// share the same base pattern — only the disparity shift differs, so there is no
// monocular edge cue in the interior).
function rngRow(seed: number): () => number {
  let s = (seed * 2654435761) >>> 0;
  return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 0x100000000; };
}
function rdsFrame(t: number): { left: Uint8Array; right: Uint8Array } {
  const left = new Uint8Array(W * H), right = new Uint8Array(W * H);
  const density = 0.45;
  const maxDisp = 8;                              // px of disparity at the blob's peak
  const depth = 0.5 + 0.5 * Math.sin(t * Math.PI * 2); // blob depth breathes 0..1
  const cx = W / 2 + Math.cos(t * Math.PI * 2) * (W * 0.18); // drift so it's clearly moving
  const cy = H / 2 + Math.sin(t * Math.PI * 2 * 0.7) * (H * 0.14);
  const rad = Math.min(W, H) * 0.28;
  for (let y = 0; y < H; y++) {
    // per-row deterministic dot field, sampled with a per-eye horizontal shift
    const base = new Uint8Array(W + 2 * maxDisp);
    const rnd = rngRow(y * 9176 + 12345);
    for (let x = 0; x < base.length; x++) base[x] = rnd() < density ? 255 : 0;
    for (let x = 0; x < W; x++) {
      const dx = x - cx, dy = y - cy;
      const r = Math.hypot(dx, dy);
      // disparity: full inside the blob, tapering to 0 at its rim, 0 outside
      const inside = r < rad ? Math.cos((r / rad) * (Math.PI / 2)) : 0;
      const disp = Math.round(inside * depth * maxDisp);
      const half = disp >> 1;
      left[y * W + x] = base[x + maxDisp + half]!;   // left eye samples shifted right
      right[y * W + x] = base[x + maxDisp - half]!;  // right eye shifted left -> crossed
    }
  }
  return { left, right };
}

// Produce the (left, right) 8bpp frames for frame index `i` of FRAMES.
const TILE_GRID = process.env.G2_TILE_GRID === "1";
function renderFrame(i: number): { left: Uint8Array; right: Uint8Array } {
  const t = i / FRAMES;
  if (SCENE === "rds") return rdsFrame(t);
  const segs = SCENE === "map" ? mapScene(t) : SCENE === "rings" ? ringsScene(t) : cubeScene(t);
  const left = renderWire(segs, -1), right = renderWire(segs, +1);
  if (TILE_GRID) { overlayTileGrid(left); overlayTileGrid(right); }
  return { left, right };
}

// -------------------------------------------------- mode-4 payload build ------
// [0x04][ zlib( left[n] ++ right[n] ) ] where n = pixels in this (sub)container.
function buildStereoPayload(left: Uint8Array, right: Uint8Array): Uint8Array {
  const n = left.length;
  const pair = new Uint8Array(n * 2);
  pair.set(left, 0);
  pair.set(right, n);
  const z = deflateSync(pair);
  const out = new Uint8Array(z.length + 1);
  out[0] = 0x04;                                  // CFW image mode 4 = stereo pair
  out.set(z, 1);
  return out;
}

// Crop a TILE_W x TILE_H sub-rectangle out of a full W x H frame (row-major 8bpp),
// keeping each pixel at its screen position — so each lens reassembles its own
// eye's full-panel image from the per-tile crops.
function cropTile(src: Uint8Array, sx: number, sy: number, tw: number, th: number): Uint8Array {
  const out = new Uint8Array(tw * th);
  for (let y = 0; y < th; y++) {
    const row = (sy + y) * W + sx;
    out.set(src.subarray(row, row + tw), y * tw);
  }
  return out;
}

// --------------------------------------------------------- BMP preview --------
// 24-bit BMP writer (no deps). Used by the dry-run preview so the stereo pair is
// inspectable without glasses: a side-by-side (parallel/cross free-view) and a
// red/cyan anaglyph (view with red-left / cyan-right glasses).
function writeBmp(path: string, width: number, height: number, rgb: (x: number, y: number) => [number, number, number]) {
  const rowSize = (width * 3 + 3) & ~3;
  const pixels = rowSize * height;
  const buf = Buffer.alloc(54 + pixels);
  buf.write("BM", 0);
  buf.writeUInt32LE(54 + pixels, 2);
  buf.writeUInt32LE(54, 10);
  buf.writeUInt32LE(40, 14);
  buf.writeInt32LE(width, 18);
  buf.writeInt32LE(height, 22); // positive -> bottom-up rows
  buf.writeUInt16LE(1, 26);
  buf.writeUInt16LE(24, 28);
  buf.writeUInt32LE(pixels, 34);
  for (let y = 0; y < height; y++) {
    const row = 54 + (height - 1 - y) * rowSize; // bottom-up
    for (let x = 0; x < width; x++) {
      const [r, g, b] = rgb(x, y);
      const o = row + x * 3;
      buf[o] = b; buf[o + 1] = g; buf[o + 2] = r; // BMP is BGR
    }
  }
  require("node:fs").writeFileSync(path, buf);
}

// ------------------------------------------------------------- main -----------
async function main() {
  console.log(`[stereo] scene=${SCENE} ${W}x${H} frames=${FRAMES} IOD=${IOD} f=${FOCAL} Zc=${ZC}`);

  // Report the disparity band across the whole animation so we can sanity-check
  // fusibility (roughly keep |disparity| within ~10 px on this small panel).
  {
    let lo = Infinity, hi = -Infinity;
    const zFar = RING_BASE + (RING_COUNT - 1) * RING_SPACING;
    const sampleZ = SCENE === "rings"
      ? [RING_NEAR, (RING_NEAR + zFar) / 2, zFar]
      : SCENE === "map"
      ? [ZC - 5, ZC - 2, ZC, ZC + 3, ZC + 6]
      : [ZC - 2, ZC - 1, ZC, ZC + 1, ZC + 2];
    for (const z of sampleZ) {
      if (z <= 0.6) continue;
      const d = FOCAL * IOD * (1 / z - 1 / ZC);   // u_L - u_R at world depth z
      lo = Math.min(lo, d); hi = Math.max(hi, d);
    }
    if (SCENE === "rds") { lo = 0; hi = 8; }
    console.log(`[stereo] disparity band ~ ${lo.toFixed(1)}..${hi.toFixed(1)} px ` +
      `(+ = pops out / crossed, - = recedes / uncrossed)`);
  }

  if (DRY_RUN) {
    const { left, right } = renderFrame(PREVIEW_FRAME);
    const dir = process.env.G2_PREVIEW_DIR ?? ".";
    const sbs = `${dir}/stereo-preview-${SCENE}-sbs.bmp`;
    const ana = `${dir}/stereo-preview-${SCENE}-anaglyph.bmp`;
    // side-by-side: left | right (free-view: parallel or cross-eyed)
    writeBmp(sbs, W * 2, H, (x, y) =>
      x < W ? gray(left[y * W + x]!) : gray(right[y * W + (x - W)]!));
    // red/cyan anaglyph: R = left eye, G+B = right eye
    writeBmp(ana, W, H, (x, y) => [left[y * W + x]!, right[y * W + x]!, right[y * W + x]!]);
    console.log(`[dry-run] wrote ${sbs} and ${ana} (frame ${PREVIEW_FRAME}). Not connecting.`);
    // A cheap correctness assertion: the two eyes must actually differ.
    let diff = 0;
    for (let k = 0; k < W * H; k++) if (left[k] !== right[k]) diff++;
    console.log(`[dry-run] left/right differ in ${diff} px (${(100 * diff / (W * H)).toFixed(1)}%) — ` +
      `${diff > 0 ? "stereo disparity present" : "WARNING: identical, no stereo"}`);
    const payload = buildStereoPayload(left, right);
    const frags = planImageFragments(payload, 4000).length;
    console.log(`[dry-run] mode-4 message: ${payload.length} B compressed ` +
      `(from ${W * H * 2} B raw pair) -> ${frags} fragment(s)/frame`);
    return;
  }

  const session = await G2Session.open();
  let magic = 100;
  const nextMagic = () => (magic = magic >= 255 ? 100 : magic + 1);
  const hb = startHeartbeat({ session, nextMagic });

  try {
    // Confirm the CFW stereo feature before streaming. The settings READ can flake
    // in the first moment after connect, so retry a few times. Distinguish the two
    // failure kinds: caps present but WITHOUT stereo => genuinely wrong firmware
    // (hard stop); every read null => most likely a flaky read on a known-CFW
    // device, so warn and proceed rather than block.
    let caps = null;
    for (let attempt = 0; attempt < 4 && !caps; attempt++) {
      if (attempt) await new Promise((r) => setTimeout(r, 600));
      caps = await queryCapabilities(session, 101 + attempt).catch(() => null);
    }
    if (caps && !hasFeature(caps, "stereo")) {
      throw new Error(`glasses report '${caps.raw}' — no 'stereo' feature. ` +
        "Flash the custom firmware (see ../README.md) and verify with detect-cfw.ts");
    }
    console.log(caps ? `[stereo] CFW ok: ${caps.raw}`
      : "[stereo] WARNING: capability read returned nothing — assuming CFW is present and continuing");

    // Clear any container left live by a previous (possibly force-killed) run —
    // the firmware tracks one StartUpPage at a time and silently rejects a fresh
    // CREATE while one is still foregrounded. Best-effort; ignore the ack.
    const pre = buildShutDown({ magic: nextMagic() });
    await session.sendPb(0xe0, pre.pb, pre.magic, { ackTimeoutMs: 2500 }).catch(() => null);
    await new Promise((r) => setTimeout(r, 200));

    const suffix = String(Date.now() % 10_000).padStart(4, "0");
    // Build the tile grid: TILE_COLS x TILE_ROWS containers of TILE_W x TILE_H that
    // tile the (centred) full frame. Single-container mode is just the 1x1 case.
    const xOff = Math.max(0, (576 - W) >> 1), yOff = Math.max(0, (288 - H) >> 1);
    type Tile = { spec: ImageContainerSpec; sx: number; sy: number; sid: number };
    const tiles: Tile[] = [];
    for (let row = 0, idx = 0; row < TILE_ROWS; row++) {
      for (let col = 0; col < TILE_COLS; col++, idx++) {
        tiles.push({
          spec: {
            name: `i${suffix}_${idx}`, containerId: 2 + idx,
            x: xOff + col * TILE_W, y: yOff + row * TILE_H, width: TILE_W, height: TILE_H,
          },
          sx: col * TILE_W, sy: row * TILE_H, sid: 1,
        });
      }
    }

    // CREATE + REBUILD can flake on the first attempt right after (re)connect (and
    // the multi-container CREATE more so); retry a few times, re-clearing state.
    let created = false;
    for (let a = 0; a < 4 && !created; a++) {
      if (a) {
        const sd = buildShutDown({ magic: nextMagic() });
        await session.sendPb(0xe0, sd.pb, sd.magic, { ackTimeoutMs: 2500 }).catch(() => null);
        await new Promise((r) => setTimeout(r, 500));
        console.log(`[stream] CREATE retry ${a}...`);
      }
      // Create ONLY the root StartUpPage — do NOT register the image tiles here. The
    // working multi-tile pipeline (g2-kit G2ImageStreamer) declares every image
    // container in a single Cmd=7 REBUILD instead; registering N tiles in the CREATE
    // makes a big multi-container CREATE the firmware won't ack (that's why 5
    // containers failed). One REBUILD below declares all tiles at once.
    const create = buildCreateStartUpPageContainer({
        name: `s${suffix}`, items: ["."], containerId: 1, captureEvents: false,
        magic: nextMagic(),
      });
      created = !!(await session.sendPb(0xe0, create.pb, create.magic, { ackTimeoutMs: ACK_MS }));
    }
    if (!created) throw new Error("CREATE did not ack after retries");

    let rebuilt = false;
    for (let a = 0; a < 4 && !rebuilt; a++) {
      if (a) { await new Promise((r) => setTimeout(r, 500)); console.log(`[stream] REBUILD retry ${a}...`); }
      const rebuild = buildImageContainers({ containers: tiles.map((t) => t.spec), magic: nextMagic() });
      rebuilt = !!(await session.sendPb(0xe0, rebuild.pb, rebuild.magic, { ackTimeoutMs: ACK_MS }));
    }
    if (!rebuilt) throw new Error("REBUILD did not ack after retries");
    await new Promise((r) => setTimeout(r, 300)); // let containers replicate to both lenses

    console.log(`[stream] streaming ${FRAMES} frames as ${TILE_COLS}x${TILE_ROWS} tile(s) of ` +
      `${TILE_W}x${TILE_H}, window=${WINDOW}, arm=${IMAGE_SEND_ARM}...`);
    const frameMs = FPS > 0 ? 1000 / FPS : 0;
    let sent = 0, sentBytes = 0, aborted = false;

    // Sliding window of in-flight acks. IMPORTANT: the firmware occasionally does
    // NOT ack a Cmd=3 image fragment even though it accepted and rendered it (see
    // g2-kit docs/images.md "ack-miss tolerance"). Treating one missed ack as fatal
    // aborts a frame that actually landed — so we tolerate a run of misses and only
    // give up when many in a row miss (a real disconnect / reboot). Image fragments
    // normally ack in well under a second, so a short per-fragment timeout keeps a
    // miss cheap rather than stalling the full ACK_MS.
    const IMG_ACK_MS = 2500;
    const MISS_TOLERANCE = 8;   // consecutive missed acks before we call the link dead
    const inflight: Array<Promise<unknown>> = [];
    let consecMiss = 0, linkDead = false;
    const awaitOldest = async (): Promise<void> => {
      const ack = await inflight.shift()!;
      if (ack === null) { if (++consecMiss >= MISS_TOLERANCE) linkDead = true; }
      else consecMiss = 0;
    };
    const sendMsg = async (pb: Uint8Array, mg: number): Promise<boolean> => {
      while (inflight.length >= WINDOW) { await awaitOldest(); if (linkDead) return false; }
      const r = await session.sendPbPipelined(0xe0, pb, mg, { ackTimeoutMs: IMG_ACK_MS, arm: IMAGE_SEND_ARM });
      inflight.push(r.ack);
      return true;
    };

    // Warm up each container: the firmware silently drops the FIRST rendered frame
    // of a freshly-created image container (g2-kit docs/images.md), so push a
    // throwaway all-black frame first — the real content renders on the next one.
    const warm = buildStereoPayload(new Uint8Array(TILE_W * TILE_H), new Uint8Array(TILE_W * TILE_H));
    for (const tile of tiles) {
      for (const frag of planImageFragments(warm, 4000)) {
        const raw = buildImageRawData({
          containerId: tile.spec.containerId, containerName: tile.spec.name, mapSessionId: tile.sid,
          mapTotalSize: warm.length, mapFragmentIndex: frag.index, mapRawData: frag.data, magic: nextMagic(),
        });
        await sendMsg(raw.pb, raw.magic);
      }
      tile.sid++;
    }
    await new Promise((r) => setTimeout(r, 250));
    consecMiss = 0; linkDead = false;   // don't let warmup misses count against the stream

    const tStart = performance.now();
    for (let i = 0; i < FRAMES && !aborted; i++) {
      const tFrame = performance.now();
      const { left, right } = renderFrame(i);
      // One mode-4 message per tile: each carries this tile's screen rectangle for
      // BOTH eyes, and the firmware gives each lens its own eye's crop.
      for (const tile of tiles) {
        const lt = cropTile(left, tile.sx, tile.sy, tile.spec.width, tile.spec.height);
        const rt = cropTile(right, tile.sx, tile.sy, tile.spec.width, tile.spec.height);
        const payload = buildStereoPayload(lt, rt);
        for (const frag of planImageFragments(payload, 4000)) {
          const raw = buildImageRawData({
            containerId: tile.spec.containerId, containerName: tile.spec.name, mapSessionId: tile.sid,
            mapTotalSize: payload.length, mapFragmentIndex: frag.index, mapRawData: frag.data,
            magic: nextMagic(),
          });
          if (!(await sendMsg(raw.pb, raw.magic))) { aborted = true; break; }
        }
        tile.sid++;
        sentBytes += payload.length;
        if (aborted) break;
      }
      if (aborted) { console.log(`[stream] frame ${i} NO_ACK — aborting`); break; }
      sent++;
      if (frameMs > 0) {
        const wait = frameMs - (performance.now() - tFrame);
        if (wait > 0) await new Promise((r) => setTimeout(r, wait));
      }
      if (sent % 30 === 0) {
        const fps = sent / ((performance.now() - tStart) / 1000);
        console.log(`[stream] ${sent}/${FRAMES}  ${fps.toFixed(2)} fps  ${(sentBytes / 1024).toFixed(0)} KiB`);
      }
    }
    while (!aborted && inflight.length) { await awaitOldest(); if (linkDead) aborted = true; }

    const elapsed = (performance.now() - tStart) / 1000;
    console.log(`\n=== RESULT (scene=${SCENE}, ${W}x${H}, ${TILE_COLS}x${TILE_ROWS} tiles) ===\n` +
      `frames sent : ${sent}${aborted ? " (aborted early)" : ""}\n` +
      `elapsed     : ${elapsed.toFixed(1)} s\n` +
      `framerate   : ${(sent / elapsed).toFixed(2)} fps\n` +
      `wire image  : ${(sentBytes / 1024).toFixed(0)} KiB (avg ${sent ? (sentBytes / sent).toFixed(0) : 0} B/frame)`);

    if (HOLD) {
      // Keep the image on the lens: re-send the last frame slowly and DON'T shut
      // the container down, so a still frame persists instead of vanishing when
      // the stream ends. Ctrl-C to stop.
      console.log("[stream] holding last frame (Ctrl-C to stop)...");
      const { left, right } = renderFrame(FRAMES - 1);
      for (;;) {
        for (const tile of tiles) {
          const lt = cropTile(left, tile.sx, tile.sy, tile.spec.width, tile.spec.height);
          const rt = cropTile(right, tile.sx, tile.sy, tile.spec.width, tile.spec.height);
          const payload = buildStereoPayload(lt, rt);
          for (const frag of planImageFragments(payload, 4000)) {
            const raw = buildImageRawData({
              containerId: tile.spec.containerId, containerName: tile.spec.name, mapSessionId: tile.sid,
              mapTotalSize: payload.length, mapFragmentIndex: frag.index, mapRawData: frag.data, magic: nextMagic(),
            });
            await sendMsg(raw.pb, raw.magic);
          }
          tile.sid++;
        }
        await new Promise((r) => setTimeout(r, 2000));
      }
    }

    // Tidy up: dismiss the container we created.
    const sd = buildShutDown({ magic: nextMagic() });
    await session.sendPb(0xe0, sd.pb, sd.magic, { ackTimeoutMs: ACK_MS });
  } finally {
    hb.stop();
    await session.close();
  }
}

function gray(v: number): [number, number, number] { return [v, v, v]; }

await main();
process.exit(0);
