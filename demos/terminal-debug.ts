#!/usr/bin/env bun
// Requires the DEBUG CFW (patches/dbg_terminal.c) flashed. Drives the terminal-mode
// hijack sequence on sid 0x30 AND decodes the firmware's internal debug records that
// the debug CFW emits on sid 0x7e (magic 0xE7, 14-byte records). This makes the
// RX/UI race that drops the content-bind visible on real hardware.
//
// Record (14 bytes LE): [E7][rec_type][state_a][event_id][state_b][00][arg u32][tick u32]
//   rec_type 1 = FSM transition: state_a=old, event_id, state_b=new
//   rec_type 2 = event enqueued: state_a=live state observed by poster, state_b=0xFF
//
//   bun terminal-debug.ts ["text"]
import { G2Session } from "g2-kit/ble";

const STATES = ["BOOTSTRAP","CLOSED","IDLE","BLOCKED","VOICE_CAPTURING","ASR_STREAMING",
  "ASR_FINAL","AGENT_PROCESSING","AGENT_INTERRUPT_CONFIRM","QUERY_PENDING",
  "QUERY_NOTIFICATION","SESSION_LIST","NEW_SESSION_PENDING"];
const EVENTS: Record<number,string> = {
  1:"DISPLAY_ENTER",8:"VOICE_START",9:"VOICE_STOP",10:"ASR_UPDATE",11:"ASR_FINAL",
  12:"ASR_FAIL",13:"INPUT_CONFIRM",14:"INPUT_CANCEL",15:"SESSION_STATUS_UPDATE",
  16:"AGENT_DONE",17:"AGENT_RESET",18:"CONTENT_APPEND(0x12)",19:"CONTENT_BIND(0x13)",
  21:"QUERY_SHOW",22:"QUERY_NOTIF_SHOW",25:"QUERY_REPLY",26:"INTERRUPT_CONFIRM_SHOW",
  27:"SESSION_LIST_SHOW",28:"SESSION_LIST_UPDATE",35:"SESSION_ID_CHANGED",38:"AGENT_INTERRUPT",
};
const sname = (i: number) => STATES[i] ?? `?${i}`;
const ename = (i: number) => EVENTS[i] ?? `evt${i}(0x${i.toString(16)})`;
function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }

function decodeDbg(pb: Uint8Array) {
  if (pb.length < 14 || pb[0] !== 0xe7) return null;
  const dv = new DataView(pb.buffer, pb.byteOffset, pb.length);
  const rec = pb[1], a = pb[2], ev = pb[3], b = pb[4];
  const arg = dv.getUint32(6, true), tick = dv.getUint32(10, true);
  if (rec === 1) return `FSM   ${sname(a)} --${ename(ev)}--> ${sname(b)}  arg=${arg} tick=${tick}`;
  if (rec === 2) return `POST  [state seen: ${sname(a)}] enqueue ${ename(ev)}  arg=${arg} tick=${tick}`;
  return `dbg rec_type=${rec} raw=${Buffer.from(pb).toString("hex")}`;
}

// --- hijack builders ---
function varint(n: number): number[] { const o: number[] = []; let v = n >>> 0;
  do { let x = v & 0x7f; v >>>= 7; if (v) x |= 0x80; o.push(x); } while (v); return o; }
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function vfield(f: number, v: number): number[] { return [...tagByte(f, 0), ...varint(v)]; }
function bfield(f: number, d: number[]): number[] { return [...tagByte(f, 2), ...varint(d.length), ...d]; }
function strb(s: string): number[] { return [...Buffer.from(s, "utf8")]; }
function build(disc: number, magic: number, payload: number[]): Uint8Array {
  return new Uint8Array([...vfield(1, disc), ...vfield(2, magic), ...bfield(disc + 2, payload)]);
}
function content(text: string, event: number): number[] {
  return [...vfield(1, 1), ...bfield(2, strb(text)), ...vfield(3, 0), ...vfield(4, 1), ...vfield(5, event), ...vfield(6, 1)];
}

const TEXT = process.argv[2] ?? "HELLO from external host";
const session = await G2Session.open();
console.log(`[dbg] connected. Listening for internal debug records on sid 0x7e...`);
session.onRawFrame((frame) => {
  if (!frame.ok) return;
  if (frame.sid === 0x7e) { const d = decodeDbg(frame.pb); if (d) console.log(`[${ts()}] «FW» ${d}`); return; }
  if (frame.sid === 0x30) console.log(`[${ts()}]   <-- sid=0x30 pb=${Buffer.from(frame.pb).toString("hex")}`);
});

let magic = 100;
async function send(disc: number, payload: number[], label: string) {
  console.log(`\n[dbg] >>> ${label} (disc=${disc} magic=${magic})`);
  await session.sendPb(0x30, build(disc, magic, payload), magic, { ackTimeoutMs: 1500 });
  magic++;
}

// clean reset then full sequence
await send(1, vfield(1, 0), "reset: leave terminal"); await Bun.sleep(2500);
await send(1, vfield(1, 2), "mode_sync ENTER");        await Bun.sleep(1500);
await send(2, vfield(1, 2), "host_status streaming");  await Bun.sleep(1500);
await send(10, vfield(1, 1), "session_id_changed id=1"); await Bun.sleep(1500);
await send(4, [...vfield(1,1), ...vfield(2,1)], "session_status thinking"); await Bun.sleep(1500);
for (const [i, chunk] of [TEXT, TEXT + " (more)", TEXT + " (final)"].entries()) {
  await send(5, content(chunk, i === 2 ? 4 : 2), `agent_content chunk ${i+1}`);
  await Bun.sleep(1200);
}
console.log("\n[dbg] sequence done; watching debug records 20s more...");
await Bun.sleep(20000);
await session.close();
process.exit(0);
