import { G2Session } from "g2-kit/ble";
import { deflateSync } from "node:zlib";
import { writeFileSync } from "node:fs";
const SID = 0x7b, MODE = 1, SS_SID = 0x7d;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const setFrame = (a: number) => send([0x46, a & 0xff, (a >>> 8) & 0xff, (a >>> 16) & 0xff, (a >>> 24) & 0xff]);
const TAB = (() => { const t = new Uint32Array(256); for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } return t; })();
const crc32 = (b: Uint8Array) => { let c = 0xffffffff; for (let i = 0; i < b.length; i++) c = TAB[(c ^ b[i]!) & 0xff]! ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
function decodeQoiGray(stream: Uint8Array, count: number): Uint8Array {
  const out = new Uint8Array(count); const index = new Uint8Array(64); let prev = 0, o = 0, i = 0;
  while (o < count && i < stream.length) {
    const b = stream[i++];
    if (b === 0xfe) { const v = stream[i++]; index[(v * 15) & 63] = v; prev = v; out[o++] = v; }
    else if ((b & 0xc0) === 0x00) { const v = index[b & 0x3f]; prev = v; out[o++] = v; }
    else if ((b & 0xc0) === 0x40) { const v = (prev + ((b & 0x3f) - 32)) & 0xff; index[(v * 15) & 63] = v; prev = v; out[o++] = v; }
    else if ((b & 0xc0) === 0xc0) { let run = (b & 0x3f) + 1; while (run-- > 0 && o < count) out[o++] = prev; }
    else throw new Error("bad qoi op");
  }
  return out;
}
function pngChunk(type: string, data: Uint8Array): Uint8Array {
  const t = new Uint8Array(4); for (let i = 0; i < 4; i++) t[i] = type.charCodeAt(i);
  const body = new Uint8Array(t.length + data.length); body.set(t, 0); body.set(data, 4);
  const out = new Uint8Array(4 + body.length + 4); const dv = new DataView(out.buffer);
  dv.setUint32(0, data.length, false); out.set(body, 4); dv.setUint32(4 + body.length, crc32(body), false); return out;
}
function encodePngGreen(px: Uint8Array, w: number, h: number): Uint8Array {
  const raw = new Uint8Array((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) { const ro = y * (w * 3 + 1); raw[ro] = 0;
    for (let x = 0; x < w; x++) { const v = px[y * w + x]!; const o = ro + 1 + x * 3; raw[o] = 0; raw[o + 1] = v; raw[o + 2] = 0; } }
  const idat = new Uint8Array(deflateSync(raw));
  const ihdr = new Uint8Array(13); const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, w, false); dv.setUint32(4, h, false); ihdr[8] = 8; ihdr[9] = 2;
  const sig = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const chunks = [sig, pngChunk("IHDR", ihdr), pngChunk("IDAT", idat), pngChunk("IEND", new Uint8Array(0))];
  const total = chunks.reduce((n, c) => n + c.length, 0); const out = new Uint8Array(total); let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.length; } return out;
}

const s = await G2Session.open({ quiet: true }); let seq = 1;
const w = async (arm: "L" | "R", pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm }); ack.catch(() => null); };
const got = new Map<number, Uint8Array>(); let lastIdx = -1;
s.onRawFrame((f: any, _r: Uint8Array, arm: string) => {
  if (!f.ok || f.sid !== SS_SID || arm !== "R") return; const p = f.pb;
  if (p.length < 8 || p[0] !== 0xa5) return;
  const idx = p[2] | (p[3] << 8); const flags = p[4]; const plen = p[6] | (p[7] << 8);
  got.set(idx, p.subarray(8, 8 + plen)); if (flags & 1) lastIdx = idx;
});

console.log("setting angle=20 (target 1)...");
await w("L", setFrame(20)); await Bun.sleep(600);
console.log("triggering capture 's' via arm R...");
await w("R", send([0x73])); await Bun.sleep(3000);

if (lastIdx < 0) { console.log("no capture received"); await s.close(); process.exit(1); }
let total = 0; for (let i = 0; i <= lastIdx; i++) total += got.get(i)?.length ?? 0;
const blob = new Uint8Array(total); let o = 0;
for (let i = 0; i <= lastIdx; i++) { const c = got.get(i); if (c) { blob.set(c, o); o += c.length; } }
const dv = new DataView(blob.buffer, blob.byteOffset, blob.length);
const wdt = dv.getUint16(6, true), hgt = dv.getUint16(8, true);
const qoi = blob.subarray(10, blob.length - 8);
const px = decodeQoiGray(qoi, wdt * hgt);
writeFileSync("/tmp/g2_slider_angle20-R.png", encodePngGreen(px, wdt, hgt));
console.log(`wrote /tmp/g2_slider_angle20-R.png (${wdt}x${hgt})`);
await s.close(); process.exit(0);
