#!/usr/bin/env bun
// Empirically test candidate wire tags for the terminal-mode oneof envelope
// (see ../docs/terminal-protocol.md). Static RE nailed the 11 OUTBOUND
// (glasses->phone) message tags via their APP_PbTerminalTxEncode* wrappers, but
// NOT the ~12 INBOUND (phone->glasses) tags -- those are only reachable via a
// function-pointer table (0x0072b178) that isn't referenced by any resolvable
// static xref (called through a runtime-computed index).
//
// terminal_action_mode_sync (confirmed: event index 0 in that table) reads a
// single byte field from the incoming submessage and, when it equals 2, calls
// FUN_0045ac72(0x30, 0, 0, 0) -- 0x30 is the confirmed terminal-mode sid, making
// this the leading candidate for "the message that actually switches the HUD
// into terminal mode" (the debug-CLI simulate path for this never produced any
// visible effect when tested live over NUS).
//
// This script sends a minimal candidate message -- outer{magic=N, tag=T{msg{1:2}}}
// -- for each still-unassigned oneof tag T in turn, over the REAL wire protocol
// (sid=0x30), and asks you to watch the lens. If mode_sync's real tag is among
// these, you should see SOME visible change right after that specific send.
//
//   bun terminal-probe.ts                  # try all 12 remaining candidate tags
//   bun terminal-probe.ts 7                # try only tag 7
//
// Env:
//   G2_PROBE_VALUE   the byte value sent in the submessage's own field 1 (default 2)
//   G2_PROBE_WAIT_MS  ms to wait after each send before moving on (default 2500)

import { G2Session } from "g2-kit/ble";

const CANDIDATE_TAGS = [3, 4, 5, 6, 7, 8, 14, 15, 16, 17, 21, 23];
const VALUE = Number(process.env.G2_PROBE_VALUE ?? "2");
const WAIT_MS = Number(process.env.G2_PROBE_WAIT_MS ?? "2500");
const SID_TERMINAL = 0x30;

const tags = process.argv[2] ? process.argv[2].split(",").map(Number) : CANDIDATE_TAGS;

// ---- minimal protobuf wire builder (varint + length-delimited only) ----
function varint(n: number): number[] {
  const out: number[] = [];
  let v = n >>> 0;
  do {
    let b = v & 0x7f;
    v >>>= 7;
    if (v) b |= 0x80;
    out.push(b);
  } while (v);
  return out;
}
function tagByte(fieldNum: number, wireType: number): number[] {
  return varint((fieldNum << 3) | wireType);
}
function strBytes(s: string): number[] {
  return [...Buffer.from(s, "utf8")];
}
// outer{ field1=magic(varint), field{T}=submessage(submsgBytes) }
function wrapOuter(magic: number, tag: number, submsg: number[]): Uint8Array {
  const outer = [
    ...tagByte(1, 0), ...varint(magic),
    ...tagByte(tag, 2), ...varint(submsg.length), ...submsg,
  ];
  return new Uint8Array(outer);
}

// Candidate submessage shapes to try per tag, since we don't know each tag's real
// field layout: (a) a single varint field (worked for tag=3/mode_sync), (b) a
// single string field at inner tag 1 (plausible for content/query text), (c) a
// string at inner tag1 + a small int at inner tag2 (matches "text, count" shape
// e.g. CLI `terminal query <text> <cnt>`).
function shapesFor(value: number, text: string): Array<{ desc: string; submsg: number[] }> {
  return [
    { desc: `varint{1:${value}}`, submsg: [...tagByte(1, 0), ...varint(value)] },
    { desc: `string{1:"${text}"}`, submsg: [...tagByte(1, 2), ...varint(text.length), ...strBytes(text)] },
    {
      desc: `string{1:"${text}"} + varint{2:3}`,
      submsg: [
        ...tagByte(1, 2), ...varint(text.length), ...strBytes(text),
        ...tagByte(2, 0), ...varint(3),
      ],
    },
  ];
}

console.log(`[probe] candidates: ${tags.join(", ")}  wait=${WAIT_MS}ms`);
console.log(`[probe] connecting...`);
const session = await G2Session.open();

try {
  let magic = 1;
  for (const tag of tags) {
    for (const shape of shapesFor(VALUE, "hi")) {
      const pb = wrapOuter(magic, tag, shape.submsg);
      console.log(`\n[probe] >>> WATCH THE LENS NOW <<< tag=${tag} shape=${shape.desc}  bytes=${Buffer.from(pb).toString("hex")}`);
      const ack = await session.sendPb(SID_TERMINAL, pb, magic, { ackTimeoutMs: 1500 });
      if (ack) {
        console.log(`[probe] tag=${tag} ${shape.desc}: ACK sid=${ack.sid} flag=${ack.flag} pb=${Buffer.from(ack.pb).toString("hex")}`);
      } else {
        console.log(`[probe] tag=${tag} ${shape.desc}: no ack (may still have taken effect silently)`);
      }
      magic = (magic % 250) + 1; // keep varint 1-byte, dodge the 3s magic-dedup
      await new Promise((r) => setTimeout(r, WAIT_MS));
    }
  }
} finally {
  await session.close();
}
console.log("\n[probe] done. Report which tag/shape (if any) produced a visible change.");
process.exit(0);
