#!/usr/bin/env bun
// Mode-runtime client for the G2 CFW (patches/runtime.c). Talks to the loader that
// was flashed ONCE and thereafter hot-loads arbitrary "mode" code payloads into RAM
// over BLE and runs them. All traffic rides a single dedicated inbound serviceID
// RUNTIME_SID = 0x7b; the CFW's rt_rx_hook (patches/runtime.c) intercepts frames on
// that sid and tail-calls the stock dispatcher for every other sid, so normal glasses
// traffic is byte-for-byte unchanged.
//
// Commands (see PROTOCOL section below; keep in sync with runtime.c RT_OP_*):
//   bun runtime.ts load <payload.bin> [mode_id]   fragment+upload a payload, then ACTIVATE
//   bun runtime.ts activate <payload.bin> [mode_id]  ACTIVATE (re-derives len+crc32 from .bin)
//   bun runtime.ts ping                           liveness probe (expects 0xA7 reply)
//   bun runtime.ts send <mode_id> <data>          SEND_TO_MODE (data = utf8, or "hex:AABB..")
//   bun runtime.ts reset                          exit active mode, free buffers
//   bun runtime.ts listen                         just print 0xA7 reply frames
//
// Options (env): LISTEN_MS (default 30000) how long to keep listening after a command
//                for the payload's proof-of-execution / reply frames before exiting.
//
// The runtime only executes + replies on the TRANSMIT lens (FW_SIDE()==1 == RIGHT arm;
// api_reply/api_send in runtime.c self-gate on that), so every frame goes out the R arm
// and every reply arrives on the R arm. Model/framing mirrors screenshot.ts & terminal-debug.ts.
import { G2Session } from "g2-kit/ble";
import { readFileSync } from "node:fs";

// ================================================================================
// PROTOCOL — byte layout on RUNTIME_SID 0x7b. MUST match patches/runtime.c RT_OP_*.
// All frames are the aa21 *payload* (pb); g2-kit wraps them in the transport envelope
// and (for pb+2>chunk) would CRC-fragment them — which we AVOID for LOAD_FRAG by
// sizing each command to fit one ~232-byte aa21 chunk, so every command maps to
// exactly one reassembled frame at the runtime's RX hook (r0=sid,r1=pb,r2=len).
//
//   opcode = pb[0]
//   RT_OP_LOAD_FRAG 0x01: [0x01][mode_id u8][frag_idx u16 LE][last u8][bytes...]
//        frag_idx==0 => runtime frees any old buffer + starts a fresh 16KiB code buffer,
//        then appends bytes; subsequent idx just append. (runtime.c uses idx==0 as the
//        reset signal and ignores mode_id/last for assembly — they are wire metadata.)
//   RT_OP_ACTIVATE  0x02: [0x02][mode_id u8][total_len u32 LE][crc32 u32 LE]
//        the runtime VERIFIES the uploaded buffer length == total_len AND crc32(buffer)
//        == crc32 (standard CRC-32 / zlib, poly 0xEDB88320) BEFORE it ever jumps in —
//        a dropped/reordered fragment fails the check and nothing executes. On pass it
//        dcache-cleans + I-cache-invalidates the buffer, then calls its Thumb entry(&api);
//        the returned mode vtable's init()/on_data() go live. Reply [0xA7][0x02][active u8]
//        (active=0 means the check failed or the payload returned no vtable). A too-short
//        ACTIVATE frame gets [0xA7][0xE0].
//   RT_OP_SEND      0x03: [0x03][mode_id u8][data...]   -> active mode's on_data(data,len)
//   RT_OP_RESET     0x04: [0x04]                         -> exit active mode, free buffers
//   RT_OP_PING      0x05: [0x05]                         -> reply [0xA7][0x05][active u8]
//
//   Reply frames (runtime -> host, on sid 0x7b) ALWAYS start with RT_MAGIC 0xA7.
//   PING reply is [0xA7][0x05][active]; any other 0xA7 frame is a payload-authored
//   proof-of-execution marker emitted via api_reply(). We print all of them.
// ================================================================================
const RUNTIME_SID = 0x7b;
const ARM = ((process.env.ARM ?? "R").toUpperCase() === "L" ? "L" : "R") as "L"|"R";
const RT_OP_LOAD_FRAG = 0x01;
const RT_OP_ACTIVATE = 0x02;
const RT_OP_SEND = 0x03;
const RT_OP_RESET = 0x04;
const RT_OP_PING = 0x05;
const RT_MAGIC = 0xa7;

// aa21 transport chunk is ~232 bytes; g2-kit appends a 2-byte CRC to the final chunk,
// so a single-chunk command must keep pb.length <= 230. LOAD_FRAG header is 5 bytes,
// leaving room for the code bytes. Stay a little under for margin.
const AA21_CHUNK = 232;
const CRC_RESERVE = 2;
const LOAD_HDR = 5; // [op][mode_id][frag_idx u16][last u8]
const FRAG_DATA_MAX = AA21_CHUNK - CRC_RESERVE - LOAD_HDR; // 225

const LISTEN_MS = Number(process.env.LISTEN_MS ?? 30000);
const ACK_TIMEOUT_MS = 500; // sid 0x7b is consumed by the hook with no ack; keep short

function ts(): string {
  return new Date().toISOString().split("T")[1]!.replace("Z", "");
}
// Standard CRC-32 (zlib / IEEE, poly 0xEDB88320, init ~0, xorout ~0) — MUST match
// runtime.c's crc32b so ACTIVATE's integrity check accepts an intact upload.
const CRC32_TAB = (() => {
  const t = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    t[n] = c >>> 0;
  }
  return t;
})();
function crc32(buf: Uint8Array): number {
  let c = 0xffffffff;
  for (let i = 0; i < buf.length; i++) c = CRC32_TAB[(c ^ buf[i]!) & 0xff]! ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}
function hex(b: Uint8Array): string {
  return Buffer.from(b).toString("hex");
}
function ascii(b: Uint8Array): string {
  return Array.from(b, (c) => (c >= 0x20 && c < 0x7f ? String.fromCharCode(c) : ".")).join("");
}

// --- frame builders (keep in sync with the PROTOCOL section) --------------------
function buildLoadFrag(modeId: number, fragIdx: number, last: boolean, data: Uint8Array): Uint8Array {
  const f = new Uint8Array(LOAD_HDR + data.length);
  f[0] = RT_OP_LOAD_FRAG;
  f[1] = modeId & 0xff;
  f[2] = fragIdx & 0xff;
  f[3] = (fragIdx >>> 8) & 0xff;
  f[4] = last ? 1 : 0;
  f.set(data, LOAD_HDR);
  return f;
}
function buildActivate(modeId: number, totalLen: number, crc: number): Uint8Array {
  const f = new Uint8Array(10);
  f[0] = RT_OP_ACTIVATE;
  f[1] = modeId & 0xff;
  f[2] = totalLen & 0xff; f[3] = (totalLen >>> 8) & 0xff; f[4] = (totalLen >>> 16) & 0xff; f[5] = (totalLen >>> 24) & 0xff;
  f[6] = crc & 0xff; f[7] = (crc >>> 8) & 0xff; f[8] = (crc >>> 16) & 0xff; f[9] = (crc >>> 24) & 0xff;
  return f;
}
function buildSend(modeId: number, data: Uint8Array): Uint8Array {
  const f = new Uint8Array(2 + data.length);
  f[0] = RT_OP_SEND;
  f[1] = modeId & 0xff;
  f.set(data, 2);
  return f;
}
function buildReset(): Uint8Array {
  return new Uint8Array([RT_OP_RESET]);
}
function buildPing(): Uint8Array {
  return new Uint8Array([RT_OP_PING]);
}

// --- reply printer --------------------------------------------------------------
function printReply(pb: Uint8Array): void {
  if (pb.length < 1 || pb[0] !== RT_MAGIC) {
    console.log(`[${ts()}] «rt» non-magic frame pb=${hex(pb)}`);
    return;
  }
  const op = pb[1];
  const body = pb.subarray(2);
  if (op === RT_OP_PING) {
    console.log(`[${ts()}] «rt» PING reply: mode ${pb[2] ? "ACTIVE" : "idle"} (0xA7 05 ${pb[2] ?? "?"})`);
    return;
  }
  console.log(
    `[${ts()}] «rt» PROOF marker op=0x${(op ?? 0).toString(16).padStart(2, "0")} ` +
      `len=${body.length} hex=${hex(body)} ascii="${ascii(body)}"`,
  );
}

// --- session helpers ------------------------------------------------------------
let seq = 1; // becomes the aa21 msgSeq (r3 subcode at the hook; runtime ignores it for 0x7b)

// Fire-and-forget write (no ack expected on sid 0x7b). Used for LOAD_FRAG throughput.
async function writeCmd(session: G2Session, pb: Uint8Array): Promise<void> {
  const magic = seq++ & 0xff;
  const { ack } = await session.sendPbPipelined(RUNTIME_SID, pb, magic, { arm: ARM });
  ack.catch(() => null); // swallow the inevitable ack timeout
}
// Blocking write with a short ack window (still tolerant of the expected timeout).
async function sendCmd(session: G2Session, pb: Uint8Array): Promise<void> {
  const magic = seq++ & 0xff;
  await session.sendPb(RUNTIME_SID, pb, magic, { arm: ARM, ackTimeoutMs: ACK_TIMEOUT_MS }).catch(() => null);
}

// --- payload upload -------------------------------------------------------------
async function uploadPayload(session: G2Session, modeId: number, blob: Uint8Array): Promise<void> {
  const nFrags = Math.max(1, Math.ceil(blob.length / FRAG_DATA_MAX));
  console.log(
    `[${ts()}] uploading ${blob.length}B payload as ${nFrags} LOAD_FRAG frame(s) ` +
      `(<=${FRAG_DATA_MAX}B each), mode_id=${modeId}`,
  );
  for (let i = 0; i < nFrags; i++) {
    const off = i * FRAG_DATA_MAX;
    const chunk = blob.subarray(off, Math.min(off + FRAG_DATA_MAX, blob.length));
    const last = i === nFrags - 1;
    await writeCmd(session, buildLoadFrag(modeId, i, last, chunk));
    if (i % 16 === 0 || last) console.log(`[${ts()}]   frag ${i}/${nFrags - 1}${last ? " (LAST)" : ""} +${chunk.length}B`);
    await Bun.sleep(15); // pace the writes so the RX ring can't overrun
  }
  console.log(`[${ts()}] upload done.`);
}

// --- arg parsing ----------------------------------------------------------------
function parseData(arg: string): Uint8Array {
  if (arg.startsWith("hex:")) {
    const h = arg.slice(4).replace(/[^0-9a-fA-F]/g, "");
    if (h.length % 2 !== 0) throw new Error("hex data must have an even number of nibbles");
    const out = new Uint8Array(h.length / 2);
    for (let i = 0; i < out.length; i++) out[i] = parseInt(h.slice(i * 2, i * 2 + 2), 16);
    return out;
  }
  return new TextEncoder().encode(arg);
}
function parseModeId(arg: string | undefined, dflt = 1): number {
  if (arg === undefined) return dflt;
  const n = arg.startsWith("0x") ? parseInt(arg, 16) : parseInt(arg, 10);
  if (!Number.isInteger(n) || n < 0 || n > 255) throw new Error(`bad mode_id: ${arg}`);
  return n;
}

function usage(): never {
  console.error(
    "usage:\n" +
      "  bun runtime.ts load <payload.bin> [mode_id]\n" +
      "  bun runtime.ts activate <payload.bin> [mode_id]   (re-derives len+crc32 from the .bin)\n" +
      "  bun runtime.ts ping\n" +
      "  bun runtime.ts send <mode_id> <data|hex:AABB..>\n" +
      "  bun runtime.ts reset\n" +
      "  bun runtime.ts listen\n" +
      "  (env LISTEN_MS controls post-command listen window)",
  );
  process.exit(2);
}

// --- main -----------------------------------------------------------------------
const [cmd, a1, a2] = process.argv.slice(2);
if (!cmd) usage();

const session = await G2Session.open();
console.log(`[${ts()}] connected. listening for 0xA7 replies on sid 0x${RUNTIME_SID.toString(16)} (R arm)...`);

// Reply listener: every 0xA7 frame on sid 0x7b is a runtime/payload reply.
session.onRawFrame((frame) => {
  if (!frame.ok || frame.sid !== RUNTIME_SID) return;
  const p = frame.pb;
  if (p.length < 1 || p[0] !== RT_MAGIC) return; // ignore our own echoes / partials
  printReply(p);
});

async function drain(ms: number): Promise<void> {
  console.log(`[${ts()}] listening ${ms}ms for replies...`);
  await Bun.sleep(ms);
}

try {
  switch (cmd) {
    case "load": {
      if (!a1) usage();
      const modeId = parseModeId(a2, 1);
      const blob = new Uint8Array(readFileSync(a1));
      const crc = crc32(blob);
      await uploadPayload(session, modeId, blob);
      console.log(`[${ts()}] ACTIVATE mode_id=${modeId} len=${blob.length} crc32=0x${crc.toString(16).padStart(8, "0")}`);
      await sendCmd(session, buildActivate(modeId, blob.length, crc));
      await drain(LISTEN_MS);
      break;
    }
    case "activate": {
      // ACTIVATE needs the payload's length + CRC32; read the same .bin that was uploaded.
      if (!a1) usage();
      const modeId = parseModeId(a2, 1);
      const blob = new Uint8Array(readFileSync(a1));
      const crc = crc32(blob);
      console.log(`[${ts()}] ACTIVATE mode_id=${modeId} len=${blob.length} crc32=0x${crc.toString(16).padStart(8, "0")}`);
      await sendCmd(session, buildActivate(modeId, blob.length, crc));
      await drain(LISTEN_MS);
      break;
    }
    case "ping": {
      console.log(`[${ts()}] PING`);
      await sendCmd(session, buildPing());
      await drain(Math.min(LISTEN_MS, 3000));
      break;
    }
    case "send": {
      if (!a1 || a2 === undefined) usage();
      const modeId = parseModeId(a1);
      const data = parseData(a2);
      console.log(`[${ts()}] SEND_TO_MODE mode_id=${modeId} data=${hex(data)} ("${ascii(data)}")`);
      await sendCmd(session, buildSend(modeId, data));
      await drain(LISTEN_MS);
      break;
    }
    case "reset": {
      console.log(`[${ts()}] RESET`);
      await sendCmd(session, buildReset());
      await drain(Math.min(LISTEN_MS, 2000));
      break;
    }
    case "listen": {
      await drain(LISTEN_MS);
      break;
    }
    default:
      usage();
  }
} finally {
  await session.close();
}
process.exit(0);
