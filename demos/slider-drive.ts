#!/usr/bin/env bun
// slider-drive.ts — a terminal "slider": hold Left/Right arrow keys to spin the onboard 3D model in
// real time. Sends 'F'+u32LE(angle) via arm-L to enable manual rotation (mode_ownanim.c's next_frame()
// picks it up through the SAME proven barrier -- no new peer protocol). 'Space' toggles stereo ('d'),
// 'Esc'/Ctrl-C releases manual mode ('A') and exits. Assumes the payload is already loaded+open+synced
// (run stereo-go.ts or equivalent first) -- this script only drives rotation, it doesn't (re)load.
import { G2Session } from "g2-kit/ble";

const SID = 0x7b, MODE = 1;
const send = (d: number[]) => Uint8Array.from([3, MODE, ...d]);
const setFrame = (angle: number) => send([0x46, angle & 0xff, (angle >>> 8) & 0xff, (angle >>> 16) & 0xff, (angle >>> 24) & 0xff]); // 'F'
const STEP = 3; // angle units per key-repeat tick (angle wraps mod 256 per full Y-turn; X-tumble = angle&255 too)

const s = await G2Session.open({ quiet: true });
let seq = 1;
const w = async (pb: Uint8Array) => { const { ack } = await s.sendPbPipelined(SID, pb, seq++ & 0xff, { arm: "L" }); ack.catch(() => null); };

let angle = 0;
console.log("slider-drive: Left/Right = rotate, Space = toggle stereo, Esc/Ctrl-C = release + exit");
console.log("(assumes mode_ownanim is already loaded+open+synced on both lenses via arm-L)");

process.stdin.setRawMode?.(true);
process.stdin.resume();
process.stdin.setEncoding("utf8");

let dirty = false;
let running = true;
process.stdin.on("data", async (key: string) => {
  if (key === "" || key === "") { // Ctrl-C or Esc
    running = false;
    await w(send([0x41])); // 'A' release manual mode
    process.stdin.setRawMode?.(false);
    await s.close();
    process.exit(0);
  } else if (key === "[D") { angle -= STEP; dirty = true; }       // Left arrow
  else if (key === "[C") { angle += STEP; dirty = true; }         // Right arrow
  else if (key === " ") { await w(send([0x64])); console.log("  (stereo toggled)"); } // 'd'
});

// Push the current angle at a steady ~30Hz whenever it changed since the last push (coalesces bursts
// of key-repeat events into a smooth stream instead of flooding one write per keystroke).
while (running) {
  if (dirty) { dirty = false; await w(setFrame(((angle % 256) + 256) % 256)); process.stdout.write(`\r  angle=${((angle % 256) + 256) % 256}   `); }
  await Bun.sleep(33);
}
