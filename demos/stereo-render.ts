// Pure stereo renderer shared by the CLI, the tweak server, and the browser
// preview. No BLE, no bun-only APIs beyond node:zlib — just params + city data
// -> a left/right 8bpp frame pair, the mode-4 payload, and an anaglyph BMP.

import { deflateSync } from "node:zlib";

export type V3 = { x: number; y: number; z: number };
export type Seg = { a: V3; b: V3; i?: number };
export type Building = { h: number; poly: [number, number][] };
export type City = { extent_m: number; buildings: Building[] };

export type RenderParams = {
  W: number;
  H: number;
  focal: number;
  iod: number;       // interocular distance -> disparity scale
  converge: number;  // zero-disparity depth Zc
  aa: boolean;       // anti-alias lines (smoother but ~4x bigger payload)
  scene: "map" | "cube";
  azimuth: number;   // orbit angle (rad)
  elev: number;      // camera tilt (rad)
  dist: number;      // camera distance
  targetY: number;   // vertical framing
  span: number;      // world half-extent the city fills
  maxBldg: number;   // building cap
};

export const DEFAULTS: RenderParams = {
  W: 576, H: 288, focal: 430, iod: 0.4, converge: 11, aa: false,
  scene: "map", azimuth: 0.75, elev: -0.52, dist: 11, targetY: 0.7, span: 4.6, maxBldg: 26,
};

const rotY = (p: V3, a: number): V3 => {
  const c = Math.cos(a), s = Math.sin(a);
  return { x: c * p.x + s * p.z, y: p.y, z: -s * p.x + c * p.z };
};
const rotX = (p: V3, a: number): V3 => {
  const c = Math.cos(a), s = Math.sin(a);
  return { x: p.x, y: c * p.y - s * p.z, z: s * p.y + c * p.z };
};

// world -> camera space (camera at origin looking +Z)
function orbit(p: RenderParams): (v: V3) => V3 {
  return (v: V3): V3 => {
    let q: V3 = { x: v.x, y: v.y - p.targetY, z: v.z };
    q = rotY(q, p.azimuth);
    q = rotX(q, p.elev);
    q.z += p.dist;
    return q;
  };
}

// per-eye projection (eyeSign -1 = left, +1 = right)
function project(p: RenderParams, v: V3, eyeSign: number): { u: number; vv: number; z: number } {
  const cx = p.W / 2, cy = p.H / 2;
  const conv = (p.focal * p.iod) / (2 * p.converge);
  const z = v.z;
  const u = cx + (p.focal * (v.x - eyeSign * (p.iod / 2))) / z - eyeSign * conv;
  const vv = cy - (p.focal * v.y) / z;
  return { u, vv, z };
}

function plot(buf: Uint8Array, W: number, H: number, x: number, y: number, a: number) {
  if (x < 0 || x >= W || y < 0 || y >= H || a <= 0) return;
  const i = y * W + x;
  const val = a > 1 ? 255 : (a * 255) | 0;
  if (val > buf[i]!) buf[i] = val;
}

function drawLine(buf: Uint8Array, W: number, H: number, aa: boolean,
                  x0: number, y0: number, x1: number, y1: number, gain: number) {
  const steep = Math.abs(y1 - y0) > Math.abs(x1 - x0);
  if (steep) { [x0, y0] = [y0, x0]; [x1, y1] = [y1, x1]; }
  if (x0 > x1) { [x0, x1] = [x1, x0]; [y0, y1] = [y1, y0]; }
  const dx = x1 - x0, dy = y1 - y0;
  const grad = dx === 0 ? 1 : dy / dx;
  let inter = y0 + grad * (Math.round(x0) - x0) + grad;
  const put = (px: number, py: number, a: number) =>
    steep ? plot(buf, W, H, py, px, a * gain) : plot(buf, W, H, px, py, a * gain);
  const xa = Math.round(x0), xb = Math.round(x1);
  put(xa, Math.round(y0), 1);
  put(xb, Math.round(y1), 1);
  for (let x = xa + 1; x < xb; x++) {
    if (aa) {
      const f = inter - Math.floor(inter);
      put(x, Math.floor(inter), 1 - f);
      put(x, Math.floor(inter) + 1, f);
    } else {
      put(x, Math.round(inter), 1);
    }
    inter += grad;
  }
}

function renderWire(p: RenderParams, segs: Seg[], eyeSign: number): Uint8Array {
  const buf = new Uint8Array(p.W * p.H);
  const NEAR = 0.6;
  for (const s of segs) {
    if (s.a.z <= NEAR && s.b.z <= NEAR) continue;
    let a = s.a, b = s.b;
    if (a.z <= NEAR || b.z <= NEAR) {
      const [inP, outP] = a.z > NEAR ? [a, b] : [b, a];
      const tt = (inP.z - NEAR) / (inP.z - outP.z);
      b = { x: inP.x + (outP.x - inP.x) * tt, y: inP.y + (outP.y - inP.y) * tt, z: NEAR + 1e-4 };
      a = inP;
    }
    const pa = project(p, a, eyeSign), pb = project(p, b, eyeSign);
    drawLine(buf, p.W, p.H, p.aa, pa.u, pa.vv, pb.u, pb.vv, s.i ?? 1);
  }
  return buf;
}

// --- scenes -----------------------------------------------------------------
function mulberry32(seed: number): () => number {
  let s = seed | 0;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function groundGrid(toCam: (v: V3) => V3, half: number, step: number, segs: Seg[]) {
  for (let g = -half; g <= half + 1e-6; g += step) {
    segs.push({ a: toCam({ x: -half, y: 0, z: g }), b: toCam({ x: half, y: 0, z: g }), i: 0.26 });
    segs.push({ a: toCam({ x: g, y: 0, z: -half }), b: toCam({ x: g, y: 0, z: half }), i: 0.26 });
  }
}

function mapScene(p: RenderParams, city: City | null): Seg[] {
  const segs: Seg[] = [];
  const toCam = orbit(p);
  groundGrid(toCam, p.span * 1.05, p.span / 5, segs);
  if (city && city.buildings.length) {
    const s = p.span / Math.max(1, city.extent_m);
    for (const b of city.buildings.slice(0, p.maxBldg)) {
      const h = b.h * s;
      const base: V3[] = b.poly.map(([x, z]) => ({ x: x * s, y: 0, z: z * s }));
      const n = base.length;
      for (let k = 0; k < n; k++) {
        const kn = (k + 1) % n;
        const t0 = { x: base[k]!.x, y: h, z: base[k]!.z };
        const t1 = { x: base[kn]!.x, y: h, z: base[kn]!.z };
        segs.push({ a: toCam(t0), b: toCam(t1), i: 1 });
        segs.push({ a: toCam(base[k]!), b: toCam(t0), i: 0.72 });
      }
    }
    return segs;
  }
  // fallback procedural city
  const rnd = mulberry32(20260717);
  const N = 6, spacing = 1.55;
  for (let gx = 0; gx < N; gx++) for (let gz = 0; gz < N; gz++) {
    if (rnd() < 0.16) continue;
    const cx = (gx - (N - 1) / 2) * spacing, cz = (gz - (N - 1) / 2) * spacing;
    const h = 0.4 + rnd() * rnd() * 2.7;
    const w = spacing * (0.42 + rnd() * 0.18), d = spacing * (0.42 + rnd() * 0.18);
    const base: V3[] = [{ x: cx - w, y: 0, z: cz - d }, { x: cx + w, y: 0, z: cz - d }, { x: cx + w, y: 0, z: cz + d }, { x: cx - w, y: 0, z: cz + d }];
    const top: V3[] = base.map((q) => ({ x: q.x, y: h, z: q.z }));
    for (let k = 0; k < 4; k++) segs.push({ a: toCam(base[k]!), b: toCam(top[k]!), i: 0.75 });
    for (let k = 0; k < 4; k++) segs.push({ a: toCam(top[k]!), b: toCam(top[(k + 1) % 4]!), i: 1 });
  }
  return segs;
}

function cubeScene(p: RenderParams): Seg[] {
  const verts: V3[] = [];
  for (const sx of [-1, 1]) for (const sy of [-1, 1]) for (const sz of [-1, 1]) verts.push({ x: sx, y: sy, z: sz });
  const half = 1.25, ay = p.azimuth, ax = p.azimuth * 0.61 + 0.4;
  const center: V3 = { x: 0, y: 0, z: p.converge };
  const pts = verts.map((v) => {
    let q: V3 = { x: v.x * half, y: v.y * half, z: v.z * half };
    q = rotX(rotY(q, ay), ax);
    return { x: center.x + q.x, y: center.y + q.y, z: center.z + q.z };
  });
  const segs: Seg[] = [];
  for (let i = 0; i < 8; i++) for (let j = i + 1; j < 8; j++) {
    const d = (verts[i]!.x !== verts[j]!.x ? 1 : 0) + (verts[i]!.y !== verts[j]!.y ? 1 : 0) + (verts[i]!.z !== verts[j]!.z ? 1 : 0);
    if (d === 1) segs.push({ a: pts[i]!, b: pts[j]!, i: 1 });
  }
  return segs;
}

// --- public API -------------------------------------------------------------
export function renderStereo(p: RenderParams, city: City | null): { left: Uint8Array; right: Uint8Array } {
  const segs = p.scene === "cube" ? cubeScene(p) : mapScene(p, city);
  return { left: renderWire(p, segs, -1), right: renderWire(p, segs, +1) };
}

// [0x04][ zlib( left[n] ++ right[n] ) ]
export function buildStereoPayload(left: Uint8Array, right: Uint8Array): Uint8Array {
  const n = left.length;
  const pair = new Uint8Array(n * 2);
  pair.set(left, 0);
  pair.set(right, n);
  const z = deflateSync(pair);
  const out = new Uint8Array(z.length + 1);
  out[0] = 0x04;
  out.set(z, 1);
  return out;
}

export function cropTile(src: Uint8Array, W: number, sx: number, sy: number, tw: number, th: number): Uint8Array {
  const out = new Uint8Array(tw * th);
  for (let y = 0; y < th; y++) {
    const row = (sy + y) * W + sx;
    out.set(src.subarray(row, row + tw), y * tw);
  }
  return out;
}

// Red/cyan anaglyph as a 24-bit BMP (browsers render BMP in <img>). R = left eye,
// G+B = right eye — view with red-left / cyan-right glasses.
export function anaglyphBmp(left: Uint8Array, right: Uint8Array, W: number, H: number): Buffer {
  const rowSize = (W * 3 + 3) & ~3;
  const pixels = rowSize * H;
  const buf = Buffer.alloc(54 + pixels);
  buf.write("BM", 0);
  buf.writeUInt32LE(54 + pixels, 2);
  buf.writeUInt32LE(54, 10);
  buf.writeUInt32LE(40, 14);
  buf.writeInt32LE(W, 18);
  buf.writeInt32LE(H, 22);
  buf.writeUInt16LE(1, 26);
  buf.writeUInt16LE(24, 28);
  buf.writeUInt32LE(pixels, 34);
  for (let y = 0; y < H; y++) {
    const row = 54 + (H - 1 - y) * rowSize;
    for (let x = 0; x < W; x++) {
      const o = row + x * 3, i = y * W + x;
      buf[o] = right[i]!;       // B
      buf[o + 1] = right[i]!;   // G
      buf[o + 2] = left[i]!;    // R
    }
  }
  return buf;
}

// Side-by-side (left | right) grayscale BMP.
export function sbsBmp(left: Uint8Array, right: Uint8Array, W: number, H: number): Buffer {
  const OW = W * 2, rowSize = (OW * 3 + 3) & ~3, pixels = rowSize * H;
  const buf = Buffer.alloc(54 + pixels);
  buf.write("BM", 0);
  buf.writeUInt32LE(54 + pixels, 2); buf.writeUInt32LE(54, 10); buf.writeUInt32LE(40, 14);
  buf.writeInt32LE(OW, 18); buf.writeInt32LE(H, 22); buf.writeUInt16LE(1, 26); buf.writeUInt16LE(24, 28);
  buf.writeUInt32LE(pixels, 34);
  for (let y = 0; y < H; y++) {
    const row = 54 + (H - 1 - y) * rowSize;
    for (let x = 0; x < OW; x++) {
      const src = x < W ? left[y * W + x]! : right[y * W + (x - W)]!;
      const o = row + x * 3;
      buf[o] = src; buf[o + 1] = src; buf[o + 2] = src;
    }
  }
  return buf;
}
