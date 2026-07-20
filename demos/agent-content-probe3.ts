#!/usr/bin/env bun
// Real field layout confirmed by BOTH independent subagents:
// tag=7 { f1:style(u8), f2:text(bytes), f3:op(u8), f4:id(u32), f5:event(u8), f6:session_id(u32) }
// event==4 triggers the "final/refresh" path in terminal_action_agent_content regardless
// of fsm_state (text still gets appended even outside AGENT_PROCESSING, per the RX decompile).
import { G2Session } from "g2-kit/ble";
function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }
function varint(n: number): number[] {
  const out: number[] = []; let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; out.push(b); } while (v);
  return out;
}
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function strField(f: number, s: string): number[] {
  const b = [...Buffer.from(s, "utf8")];
  return [...tagByte(f, 2), ...varint(b.length), ...b];
}
function varField(f: number, v: number): number[] { if (v === 0) return []; return [...tagByte(f, 0), ...varint(v)]; }
function wrapOuter(magic: number, tag: number, submsg: number[]): Uint8Array {
  return new Uint8Array([...tagByte(1, 0), ...varint(magic), ...tagByte(tag, 2), ...varint(submsg.length), ...submsg]);
}
const START_MAGIC = Number(process.argv[2] ?? "5");
const SESSION_ID = Number(process.argv[3] ?? "1");
const TEXT = process.argv[4] ?? "hello from external hijack";
const session = await G2Session.open();
console.log(`[content] connected. magic=${START_MAGIC} session_id=${SESSION_ID} text="${TEXT}"`);
session.onRawFrame((frame, raw, arm) => {
  if (!frame.ok) return;
  console.log(`[${ts()}] ${arm} sid=0x${frame.sid.toString(16)} pb=${Buffer.from(frame.pb).toString("hex")}`);
});
let magic = START_MAGIC;
console.log("[content] waiting 5s baseline, check lens...");
await new Promise(r => setTimeout(r, 5000));
{
  const sub = [
    ...varField(1, 1),          // style = 1 (hi)
    ...strField(2, TEXT),        // text
    ...varField(3, 1),           // op = 1 (add)
    ...varField(4, 1),            // id = 1
    ...varField(5, 4),             // event = 4 (final/refresh)
    ...varField(6, SESSION_ID),     // session_id
  ];
  const pb = wrapOuter(magic, 7, sub);
  console.log(`\n[content] >>> agent_content magic=${magic} bytes=${Buffer.from(pb).toString("hex")}`);
  const ack = await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  console.log(ack ? `[content] ack: ${Buffer.from(ack.pb).toString("hex")}` : "[content] no direct ack");
  magic++;
}
console.log("[content] waiting 10s -- CHECK LENS NOW for any text/content change!");
await new Promise(r => setTimeout(r, 10000));
console.log(`[content] next magic would be ${magic}`);
await new Promise(r => setTimeout(r, 8000));
await session.close();
process.exit(0);
