#!/usr/bin/env bun
// Probe the G2's Nordic UART Service (NUS) to test whether the firmware's debug
// console (the "terminal <subcommand>" shell — see docs/terminal-protocol.md) is
// reachable over BLE, without any firmware modification.
//
// Background: static RE of g2_2.2.4.34.bin found the standard NUS UUIDs
// (6E400001/2/3) embedded in the SAME live GATT table as the app's normal
// EvenHub services (a real xref from what looks like a master service-registration
// array — not obviously dead code), plus a working NUS send path
// (APP_BleNusSendDataMsg, decompiled). Whether NUS *input* reaches the debug shell
// parser could not be confirmed statically — this script settles it empirically.
//
// This is READ-MOSTLY and LOW RISK: a normal BLE central connect + GATT
// discover + characteristic write/notify, exactly like any BLE app would do.
// It does NOT flash or modify firmware.
//
//   bun nus-probe.ts                       # scan, connect, sweep several candidate framings
//   bun nus-probe.ts 'terminal query hi 3' # sweep using this as the plain-text candidate
//   G2_NUS_SIDE=L bun nus-probe.ts         # only try the left arm (default: try both)
//   G2_NUS_SWEEP=0 bun nus-probe.ts 'foo'  # send exactly one framing (CRLF), no sweep
//
// Env:
//   G2_NUS_SIDE        L | R | both (default: both)
//   G2_NUS_TIMEOUT     scan timeout ms (default 20000)
//   G2_NUS_SWEEP       0 to disable the multi-framing sweep (default: on)
//   G2_NUS_PROBE_WAIT  ms to wait for a reply after each probe in the sweep (default 1500)

import noble from "@stoprocent/noble";
import type { Peripheral, Characteristic } from "@stoprocent/noble";

const NAME_RE = /(?:even\s+)?G\d+_(\d+)_([LR])_/i;
const NUS_SERVICE = "6e400001b5a3f393e0a9e50e24dcca9e";
const NUS_RX = "6e400002b5a3f393e0a9e50e24dcca9e";       // write (phone -> glasses)
const NUS_TX = "6e400003b5a3f393e0a9e50e24dcca9e";       // notify (glasses -> phone)

const SIDE = (process.env.G2_NUS_SIDE ?? "both").toUpperCase();
const TIMEOUT = Number(process.env.G2_NUS_TIMEOUT ?? "20000");
const CMD = process.argv[2] ?? "terminal cache";
const SWEEP = process.env.G2_NUS_SWEEP !== "0";           // default on: try several framings/handshakes
const PROBE_WAIT = Number(process.env.G2_NUS_PROBE_WAIT ?? "1500"); // ms between probes in a sweep

function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }

function r(p: Peripheral): string {
  return (p as any).address || p.id;
}

async function scanFor(side: "L" | "R" | "BOTH", timeoutMs: number): Promise<Peripheral[]> {
  if (noble.state !== "poweredOn") await noble.waitForPoweredOnAsync(6000);
  const found = new Map<string, Peripheral>();
  return new Promise((resolve, reject) => {
    const onDiscover = (p: Peripheral) => {
      const name = p.advertisement.localName || "";
      const m = NAME_RE.exec(name);
      if (!m) return;
      const armSide = m[2]!.toUpperCase();
      if (side !== "BOTH" && armSide !== side) return;
      if (!found.has(armSide)) {
        console.log(`[${ts()}] found ${armSide} arm: ${name} (${r(p)})`);
        found.set(armSide, p);
      }
    };
    noble.on("discover", onDiscover);
    noble.startScanningAsync([], true).catch(reject);
    setTimeout(() => {
      noble.off("discover", onDiscover);
      noble.stopScanningAsync().then(() => resolve([...found.values()]));
    }, timeoutMs);
  });
}

async function probeArm(p: Peripheral): Promise<boolean> {
  const label = p.advertisement.localName || r(p);
  console.log(`[${ts()}] connecting to ${label}...`);
  await p.connectAsync();
  const { characteristics } = await p.discoverAllServicesAndCharacteristicsAsync();
  const rx = characteristics.find((c: Characteristic) => c.uuid.toLowerCase() === NUS_RX);
  const tx = characteristics.find((c: Characteristic) => c.uuid.toLowerCase() === NUS_TX);
  const svcSeen = characteristics.some((c: Characteristic) =>
    (c as any)._serviceUuid?.toLowerCase?.() === NUS_SERVICE);

  console.log(`[${ts()}] ${label}: ${characteristics.length} characteristics total, ` +
    `NUS service seen=${svcSeen}, RX=${!!rx}, TX=${!!tx}`);

  if (!rx || !tx) {
    console.log(`[${ts()}] ${label}: NUS not present on this arm.`);
    await p.disconnectAsync();
    return false;
  }
  const rxChar = rx;

  let gotReply = false;
  let lastReplyAscii = "";
  tx.on("data", (data: Buffer) => {
    gotReply = true;
    const raw = new Uint8Array(data);
    const ascii = Buffer.from(raw).toString("latin1").replace(/[^\x20-\x7e\n\r]/g, ".");
    lastReplyAscii = ascii.trim();
    console.log(`[${ts()}] ${label} TX <- ${raw.length}B  hex=${Buffer.from(raw).toString("hex")}`);
    console.log(`           ascii="${lastReplyAscii}"`);
  });
  await tx.subscribeAsync();

  async function send(desc: string, text: string, waitMs = PROBE_WAIT): Promise<void> {
    console.log(`[${ts()}] ${label}: sending ${desc}`);
    lastReplyAscii = "";
    try {
      await rxChar.writeAsync(Buffer.from(text, "ascii"), false);
    } catch (e) {
      console.log(`[${ts()}] ${label}: write failed: ${e}`);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, waitMs));
  }

  // Confirmed handshake: "AT^NUS=1\r\n" -> "NUS+OK" (the exact string embedded in
  // the firmware). Gate the terminal-mode sequence on actually seeing that reply,
  // since the later commands only make sense once the AT pipe has acked.
  await send("AT^NUS=1\\r\\n (confirmed handshake)", "AT^NUS=1\r\n");
  const handshakeOk = lastReplyAscii.includes("NUS+OK");
  console.log(`[${ts()}] ${label}: handshake ${handshakeOk ? "OK" : "NOT confirmed"}`);

  if (SWEEP) {
    // Fuller activation sequence: "terminal mode 1" alone had no visible effect
    // (per live test). Hypothesis: the screen only actually appears once there's
    // an active "host" session (TERMINAL_UI_EVENT_DISPLAY_ENTER likely gates on
    // this) -- "terminal host 2" simulates a host going into the "streaming"
    // state. Try mode -> host -> a lens-visible command, watching at each step.
    await send("\"terminal\"\\r\\n (expect usage/help if shell is live)", "terminal\r\n");
    await send("\"terminal mode 1\"\\r\\n (enter terminal mode)", "terminal mode 1\r\n", PROBE_WAIT + 500);
    console.log(`[${ts()}] ${label}: >>> WATCH THE LENS NOW (mode 1) <<<`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await send("\"terminal host 2\"\\r\\n (simulate host: streaming)", "terminal host 2\r\n", PROBE_WAIT + 500);
    console.log(`[${ts()}] ${label}: >>> WATCH THE LENS NOW (host 2 / streaming) <<<`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await send("\"terminal content hi rep hello world\"\\r\\n (agent content, should show text)",
      "terminal content hi rep hello world\r\n", PROBE_WAIT + 1000);
    console.log(`[${ts()}] ${label}: >>> WATCH THE LENS NOW (content) <<<`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await send("\"terminal query hello 3\"\\r\\n (should show a query notification on-lens)",
      "terminal query hello 3\r\n", PROBE_WAIT + 1500);
    console.log(`[${ts()}] ${label}: >>> WATCH THE LENS NOW (query) <<<`);
    await new Promise((resolve) => setTimeout(resolve, 1500));
    await send(`${JSON.stringify(CMD)}\\r\\n`, CMD + "\r\n");
  } else {
    await send(JSON.stringify(CMD), CMD + "\r\n");
  }

  if (!gotReply) {
    console.log(`[${ts()}] ${label}: no reply to any probe (console may be silent, gated, or not wired to NUS-RX).`);
  }
  await p.disconnectAsync();
  return gotReply;
}

const side = (SIDE === "L" || SIDE === "R") ? SIDE : "BOTH";
console.log(`[${ts()}] scanning for G2 arm(s) (side=${side}, timeout=${TIMEOUT}ms)...`);
const arms = await scanFor(side as any, TIMEOUT);
if (arms.length === 0) {
  console.error("no G2 arm found advertising. Power on the glasses and make sure they are NOT connected to the phone.");
  process.exit(1);
}

let any = false;
for (const p of arms) {
  try {
    if (await probeArm(p)) any = true;
  } catch (e) {
    console.error(`probe failed: ${e}`);
  }
}

console.log(any
  ? "\n=== NUS console appears REACHABLE over BLE (got a reply). ==="
  : "\n=== No confirmed NUS console reply. Either NUS isn't wired to the shell, or this command produced no output. ===");
process.exit(0);
