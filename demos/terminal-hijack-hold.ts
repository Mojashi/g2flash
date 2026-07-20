#!/usr/bin/env bun
// Variant of terminal-hijack.ts that tries to make agent text PERSIST on the lens:
//   * never sends event=4 (final) -- staying in the "agent is still streaming" display
//   * re-asserts session_status(status=1 thinking) between content chunks to hold
//     AGENT_PROCESSING(7) (content is dropped in any other state)
//   * tight timing
// Hypothesis: event=4 completes the turn and clears/returns to IDLE, so we avoid it.
//
//   bun terminal-hijack-hold.ts ["your text"]
import { G2Session } from "g2-kit/ble";

function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }
function varint(n: number): number[] { const o: number[] = []; let v = n >>> 0;
  do { let b = v & 0x7f; v >>>= 7; if (v) b |= 0x80; o.push(b); } while (v); return o; }
function tagByte(f: number, w: number): number[] { return varint((f << 3) | w); }
function vfield(f: number, v: number): number[] { return [...tagByte(f, 0), ...varint(v)]; }
function bfield(f: number, d: number[]): number[] { return [...tagByte(f, 2), ...varint(d.length), ...d]; }
function strb(s: string): number[] { return [...Buffer.from(s, "utf8")]; }
function build(disc: number, magic: number, payload: number[]): Uint8Array {
  return new Uint8Array([...vfield(1, disc), ...vfield(2, magic), ...bfield(disc + 2, payload)]);
}
// agent_content: style=1, text, op=0(add), id=1, event, session_id=1
function content(text: string, event: number): number[] {
  return [...vfield(1, 1), ...bfield(2, strb(text)), ...vfield(3, 0),
          ...vfield(4, 1), ...vfield(5, event), ...vfield(6, 1)];
}

const TEXT = process.argv[2] ?? "Hijacked agent output from macOS";
const session = await G2Session.open();
console.log(`[hold] connected. WATCH THE LENS.`);
session.onRawFrame((frame) => {
  if (!frame.ok || frame.sid !== 0x30) return;
  console.log(`[${ts()}]   <-- sid=0x30 flag=0x${frame.flag.toString(16)} pb=${Buffer.from(frame.pb).toString("hex")}`);
});

let magic = 150;
async function send(disc: number, payload: number[], label: string) {
  const pb = build(disc, magic, payload);
  console.log(`[hold] >>> ${label} (disc=${disc} magic=${magic})`);
  await session.sendPb(0x30, pb, magic, { ackTimeoutMs: 1500 });
  magic++;
}

await send(1, vfield(1, 2), "mode_sync(enter)");            await Bun.sleep(1200);
await send(2, vfield(1, 2), "host_status(streaming)");      await Bun.sleep(1200);
await send(10, vfield(1, 1), "session_id_changed(id=1)");   await Bun.sleep(1200);
await send(4, [...vfield(1, 1), ...vfield(2, 1)], "session_status(thinking)"); await Bun.sleep(1000);

// stream content chunks, event=2 only, re-asserting thinking between them; NO final.
const words = TEXT.split(" ");
let acc = "";
for (let i = 0; i < words.length; i++) {
  acc += (i ? " " : "") + words[i];
  await send(5, content(acc, 2), `content "${acc}"`);
  await Bun.sleep(700);
  if (i % 2 === 1) { await send(4, [...vfield(1, 1), ...vfield(2, 1)], "re-assert thinking"); await Bun.sleep(400); }
}

console.log("\n[hold] streamed all text WITHOUT a final event. Holding 25s -- is the text visible on the lens?");
await Bun.sleep(25000);
await session.close();
process.exit(0);
