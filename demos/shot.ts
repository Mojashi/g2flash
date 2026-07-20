#!/usr/bin/env bun
// Screenshot client for the G2 CFW (patches/screenshot.c). Requests an on-lens
// capture, collects the grayscale-QOI fragments the firmware streams back on sid
// 0x7d, reassembles + verifies (length + CRC-32) them, QOI-decodes to a grayscale
// raster and writes a PNG (+ PGM) to disk.
//
//   bun screenshot.ts [out_basename]
//
// Protocol (must match patches/screenshot.c and scratchpad/qoi_ref.py):
//   Fragment (aa21 frame on sid 0x7d): [0]=0xA5 magic [1]=0x01 ver [2..3]=frag_index
//     u16 LE [4]=flags(bit0=LAST) [5]=0 [6..7]=payload_len u16 LE [8..]=payload.
//   Reassembled blob: "G2SS", ver, flags(bit0=up-filter), w:u16, h:u16, QOI...,
//     trailer{qoi_len:u32, crc32:u32}. CRC-32 (zlib/PNG, poly 0xEDB88320) over the
//     QOI bytes only. QOI is the 1-channel grayscale variant (see decodeQoiGray).
import { G2Session } from "g2-kit/ble";
import { deflateSync } from "node:zlib";
import { writeFileSync } from "node:fs";

const SS_SID = 0x7d;
const SS_FRAG_MAGIC = 0xa5;
const SS_VER = 0x01;
const CAPTURE_TIMEOUT_MS = 20000;   // wall-clock budget to receive the whole frame
const IDLE_TIMEOUT_MS = 4000;       // give up if no new fragment arrives for this long

// ---- CRC-32 (zlib/PNG), table built from reflected poly 0xEDB88320 -------------
const CRC_TABLE = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(buf: Uint8Array, seed = 0xffffffff): number {
  let c = seed;
  for (let i = 0; i < buf.length; i++) c = CRC_TABLE[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

// ---- grayscale QOI decoder (1 channel) -----------------------------------------
// ops: 0x00..0x3F INDEX; 0x40..0x7F DIFF (d=(b&0x3F)-32); 0xC0..0xFD RUN
// (n=(b&0x3F)+1); 0xFE GRAY literal. HASH(v)=(v*15)&63. prev/index update as in
// scratchpad/qoi_ref.py (index on DIFF/GRAY; prev on INDEX/DIFF/GRAY).
function decodeQoiGray(stream: Uint8Array, count: number): Uint8Array {
  const out = new Uint8Array(count);
  const index = new Uint8Array(64);
  let prev = 0;
  let o = 0;
  let i = 0;
  while (o < count && i < stream.length) {
    const b = stream[i++];
    if (b === 0xfe) {                       // GRAY literal
      const v = stream[i++];
      index[(v * 15) & 63] = v;
      prev = v;
      out[o++] = v;
    } else if ((b & 0xc0) === 0x00) {       // INDEX
      const v = index[b & 0x3f];
      prev = v;
      out[o++] = v;
    } else if ((b & 0xc0) === 0x40) {       // DIFF
      const v = (prev + ((b & 0x3f) - 32)) & 0xff;
      index[(v * 15) & 63] = v;
      prev = v;
      out[o++] = v;
    } else if ((b & 0xc0) === 0xc0) {       // RUN
      let run = (b & 0x3f) + 1;
      while (run-- > 0 && o < count) out[o++] = prev;
    } else {
      throw new Error(`bad QOI op 0x${b.toString(16)} at ${i - 1}`);
    }
  }
  if (o !== count) throw new Error(`QOI decoded ${o} px, expected ${count}`);
  return out;
}

function reverseUpFilter(px: Uint8Array, w: number, h: number): Uint8Array {
  for (let y = 1; y < h; y++)
    for (let x = 0; x < w; x++)
      px[y * w + x] = (px[y * w + x] + px[(y - 1) * w + x]) & 0xff;
  return px;
}

// ---- reassembled-blob parse (verifies dims, length, CRC) -----------------------
function parseBlob(blob: Uint8Array): { w: number; h: number; flags: number; px: Uint8Array } {
  if (blob.length < 18 || blob[0] !== 0x47 || blob[1] !== 0x32 || blob[2] !== 0x53 || blob[3] !== 0x53)
    throw new Error("bad blob magic (expected 'G2SS')");
  const dv = new DataView(blob.buffer, blob.byteOffset, blob.length);
  const ver = blob[4];
  const flags = blob[5];
  const w = dv.getUint16(6, true);
  const h = dv.getUint16(8, true);
  const qoiLen = dv.getUint32(blob.length - 8, true);
  const crc = dv.getUint32(blob.length - 4, true);
  const qoi = blob.subarray(10, blob.length - 8);
  if (qoi.length !== qoiLen) throw new Error(`qoi_len ${qoiLen} != ${qoi.length}`);
  const got = crc32(qoi);
  if (got !== crc) throw new Error(`CRC mismatch: got 0x${got.toString(16)} want 0x${crc.toString(16)}`);
  console.log(`[shot] blob ok: ver=${ver} ${w}x${h} flags=0x${flags.toString(16)} qoi=${qoiLen}B crc=0x${crc.toString(16)}`);
  let px = decodeQoiGray(qoi, w * h);
  if (flags & 1) px = reverseUpFilter(px, w, h);
  return { w, h, flags, px };
}

// ---- minimal 8-bit grayscale PNG encoder ---------------------------------------
function pngChunk(type: string, data: Uint8Array): Uint8Array {
  const t = new Uint8Array(4);
  for (let i = 0; i < 4; i++) t[i] = type.charCodeAt(i);
  const body = new Uint8Array(t.length + data.length);
  body.set(t, 0); body.set(data, 4);
  const out = new Uint8Array(4 + body.length + 4);
  const dv = new DataView(out.buffer);
  dv.setUint32(0, data.length, false);
  out.set(body, 4);
  dv.setUint32(4 + body.length, crc32(body), false);
  return out;
}
function encodePngGray(px: Uint8Array, w: number, h: number): Uint8Array {
  // GREEN RGB — matches the G2's green microLED (intensity -> green channel, R=B=0).
  const raw = new Uint8Array((w * 3 + 1) * h);    // filter byte + 3 bytes/px per scanline
  for (let y = 0; y < h; y++) {
    const ro = y * (w * 3 + 1); raw[ro] = 0;
    for (let x = 0; x < w; x++) { const v = px[y * w + x]!; const o = ro + 1 + x * 3; raw[o] = 0; raw[o + 1] = v; raw[o + 2] = 0; }
  }
  const idat = new Uint8Array(deflateSync(raw));
  const ihdr = new Uint8Array(13);
  const dv = new DataView(ihdr.buffer);
  dv.setUint32(0, w, false); dv.setUint32(4, h, false);
  ihdr[8] = 8;  // bit depth
  ihdr[9] = 2;  // color type 2 = truecolor RGB
  const sig = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);
  const chunks = [sig, pngChunk("IHDR", ihdr), pngChunk("IDAT", idat), pngChunk("IEND", new Uint8Array(0))];
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const out = new Uint8Array(total);
  let off = 0;
  for (const c of chunks) { out.set(c, off); off += c.length; }
  return out;
}
function encodePgm(px: Uint8Array, w: number, h: number): Uint8Array {
  const header = new TextEncoder().encode(`P5\n${w} ${h}\n255\n`);
  const out = new Uint8Array(header.length + px.length);
  out.set(header, 0); out.set(px, header.length);
  return out;
}

// ---- fragment reassembly -------------------------------------------------------
async function collectCapture(session: G2Session, targetArm: string): Promise<Uint8Array> {
  const got = new Map<number, Uint8Array>();
  let lastIndex = -1;
  return new Promise<Uint8Array>((resolve, reject) => {
    let idle: ReturnType<typeof setTimeout>;
    const overall = setTimeout(() => finish("overall timeout"), CAPTURE_TIMEOUT_MS);
    const bump = () => { clearTimeout(idle); idle = setTimeout(() => finish("idle timeout"), IDLE_TIMEOUT_MS); };

    const off = session.onRawFrame((frame, _raw, arm) => {
      if (!frame.ok || frame.sid !== SS_SID) return;
      if (String(arm).toUpperCase() !== targetArm) return;
      const p = frame.pb;
      if (p.length < 8 || p[0] !== SS_FRAG_MAGIC || p[1] !== SS_VER) return;
      const dv = new DataView(p.buffer, p.byteOffset, p.length);
      const idx = dv.getUint16(2, true);
      const flags = p[4];
      const plen = dv.getUint16(6, true);
      if (8 + plen > p.length) return;
      if (!got.has(idx)) {
        got.set(idx, p.subarray(8, 8 + plen));
        if (idx % 32 === 0 || flags & 1)
          console.log(`[shot] frag ${idx}${flags & 1 ? " (LAST)" : ""} arm=${arm} +${plen}B  total=${got.size}`);
      }
      if (flags & 1) lastIndex = idx;
      bump();
      tryComplete();
    });

    function tryComplete() {
      if (lastIndex < 0) return;
      for (let i = 0; i <= lastIndex; i++) if (!got.has(i)) return;
      finish(null);
    }
    function finish(err: string | null) {
      clearTimeout(overall); clearTimeout(idle); off();
      if (err && lastIndex < 0) return reject(new Error(`capture failed: ${err}, no LAST fragment (got ${got.size} frags)`));
      const missing: number[] = [];
      if (lastIndex < 0) return reject(new Error(`capture failed: ${err}`));
      for (let i = 0; i <= lastIndex; i++) if (!got.has(i)) missing.push(i);
      if (missing.length)
        return reject(new Error(`missing ${missing.length} fragment(s): ${missing.slice(0, 20).join(",")}${missing.length > 20 ? "..." : ""}`));
      let total = 0;
      for (let i = 0; i <= lastIndex; i++) total += got.get(i)!.length;
      const blob = new Uint8Array(total);
      let o = 0;
      for (let i = 0; i <= lastIndex; i++) { const c = got.get(i)!; blob.set(c, o); o += c.length; }
      resolve(blob);
    }
  });
}

// ---- capture trigger -----------------------------------------------------------
// Ask the CFW to take a screenshot. The firmware's cap_rx_hook (patches/screenshot.c)
// replaces the universal inbound-frame dispatcher call, so a frame on the otherwise-
// unused serviceID 0x7d whose payload begins with the capture opcode triggers the
// capture. Sent on the RIGHT arm because only the transmitting lens (FW_SIDE()==1)
// captures + streams (the hook self-gates); a left-arm copy would just no-op.
const CAP_TRIGGER_SID = 0x7b;   // RUNTIME_SID: trigger the loader payload (mode_screenshot)
async function requestCapture(session: G2Session): Promise<void> {
  const pb = new Uint8Array([0x03, 0x01, 0x73]); // RT_OP_SEND 's'
  await session.sendPb(CAP_TRIGGER_SID, pb, 0x02, { ackTimeoutMs: 400, arm: "R" }).catch(() => null); // R only (clean)
}

// ---- main ----------------------------------------------------------------------
const outBase = process.argv[2] ?? `g2shot-${new Date().toISOString().replace(/[:.]/g, "-")}`;

const session = await G2Session.open();
console.log(`[shot] connected. triggering mode_screenshot via sid 0x${CAP_TRIGGER_SID.toString(16)}...`);

const pL = collectCapture(session, "L");
const pR = collectCapture(session, "R");
await requestCapture(session);
const settled = await Promise.allSettled([pL, pR]);
for (const [i, arm] of [[0, "L"], [1, "R"]] as const) {
  const r = settled[i];
  if (r.status !== "fulfilled") { console.error(`[shot] ${arm}: ${(r.reason as Error).message}`); continue; }
  try {
    const { w, h, px } = parseBlob(r.value);
    writeFileSync(`${outBase}-${arm}.png`, encodePngGray(px, w, h));
    console.log(`[shot] wrote ${outBase}-${arm}.png (${w}x${h}, lens ${arm})`);
  } catch (e) { console.error(`[shot] ${arm} decode: ${(e as Error).message}`); }
}
await session.close();
process.exit(0);
