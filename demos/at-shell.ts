#!/usr/bin/env bun
// AT-command engineering-shell probe for the G2 glasses.
//
// The firmware exposes an AT^ console (AT_Handler, [at.core]) wired to a BLE
// characteristic (profile_nus.c / APP_BleNusHandlerInit). This tool:
//   1. connects, ENUMERATES every GATT service+characteristic (to reveal whether the
//      AT shell lives on the Even command char 2760-5401 or a separate Nordic UART
//      service 6E40xxxx), then
//   2. attaches a RAW notify listener to every notify-capable characteristic (AT
//      replies are plain text like "AT^INFO+OK:...", NOT aa21 envelopes), then
//   3. sends ONE AT command as raw ASCII + CRLF to the write char and prints every
//      byte that comes back.
//
// SAFETY: only read-only commands run by default. Destructive AT verbs are blocked
// unless FORCE=1 is set. This never sends a protobuf/aa21 command — just the raw AT line.
//
//   bun at-shell.ts                 # default: AT^INFO
//   bun at-shell.ts 'AT^IMU_EULER'  # head roll/pitch/yaw
//   bun at-shell.ts 'AT^ALS_READ'   # ambient light
//   bun at-shell.ts 'AT^LS'         # list files
//   TERM=cr bun at-shell.ts ...     # use \r instead of \r\n (env TERM: crlf|cr|lf|none)
import { G2Session } from "g2-kit/ble";

const cmd = (process.argv[2] ?? "AT^INFO").trim();
const verb = cmd.split(/[ =]/)[0];

// read-only / observe-only verbs — safe to fire
const SAFE = new Set([
  "AT", "AT^INFO", "AT^IMU_EULER", "AT^IMU_RAWDATA", "AT^ALS_READ", "AT^ALS_SCALE_READ",
  "AT^BRIGHTNESS_READ", "AT^BleGetMac", "AT^PSN", "AT^psn", "AT^LS", "AT^SCRN_X",
  "AT^SCRN_Y", "AT^thread", "AT^dump", "AT^BLES", "AT^INFO", "AT^TP", "AT^EM9305",
]);
// destructive / state-changing — refuse unless FORCE=1
const DANGER = new Set([
  "AT^RESET", "AT^RM", "AT^MKDIR", "AT^CLEANBOND", "AT^BLECleanBond", "AT^BLEMC",
  "AT^BLEADV", "AT^LOGTYPE", "AT^BLERingSend",
]);
if (DANGER.has(verb) && process.env.FORCE !== "1") {
  console.error(`REFUSING '${verb}' — destructive/state-changing. Re-run with FORCE=1 only if you are sure.`);
  process.exit(2);
}
if (!SAFE.has(verb) && process.env.FORCE !== "1") {
  console.error(`'${verb}' is not on the read-only allowlist. Re-run with FORCE=1 to send anyway.`);
  process.exit(2);
}

const TERMS: Record<string, string> = { crlf: "\r\n", cr: "\r", lf: "\n", none: "" };
const term = TERMS[process.env.TERM_MODE ?? "crlf"] ?? "\r\n";

function ts() { return new Date().toISOString().split("T")[1]!.replace("Z", ""); }
function show(tag: string, d: Buffer) {
  const asc = Array.from(d, (c) => (c >= 0x20 && c < 0x7f ? String.fromCharCode(c) : ".")).join("");
  console.log(`[${ts()}] «${tag}» ${d.length}B hex=${d.toString("hex")}  ascii="${asc}"`);
}

const session = await G2Session.open({ quiet: false });
console.log(`[${ts()}] connected.`);

// (1) enumerate GATT on both arms (diagnostic: find the AT/NUS channel)
for (const arm of [session.right, session.left]) {
  const p: any = (arm as any).peripheral;
  const svcs = p?.services ?? [];
  console.log(`\n=== [${arm.label}] GATT services/characteristics ===`);
  for (const s of svcs) {
    const chs = (s.characteristics ?? []).map((c: any) => `${c.uuid}(${(c.properties ?? []).join("/")})`).join(", ");
    console.log(`  svc ${s.uuid}: ${chs}`);
  }
  // (2) raw-notify EVERY notify/indicate characteristic on this arm
  const armed: string[] = [];
  for (const s of svcs) for (const c of (s.characteristics ?? [])) {
    const props: string[] = c.properties ?? [];
    if (props.includes("notify") || props.includes("indicate")) {
      try { await c.subscribeAsync?.(); armed.push(c.uuid); } catch (e) { console.log(`  subscribe FAIL ${c.uuid}: ${e}`); }
      c.on?.("data", (d: Buffer) => show(`${arm.label} ${c.uuid}`, d));
    }
  }
  console.log(`  [${arm.label}] notify-armed: ${armed.join(", ")}`);
}

// bonus: read the standard Device Information Service (180a) — free FW/serial/model
for (const arm of [session.right]) {
  const p: any = (arm as any).peripheral;
  const dis = (p?.services ?? []).find((s: any) => s.uuid.replace(/-/g, "").toLowerCase().includes("180a"));
  for (const c of (dis?.characteristics ?? [])) {
    try { const v: Buffer = await c.readAsync(); console.log(`[${arm.label} DIS ${c.uuid}] ${JSON.stringify(v.toString("latin1"))}`); } catch {}
  }
}

// (3) BRUTE-FORCE the AT input channel: send "<cmd>\r\n" to EVERY writable characteristic
// on the right arm and watch which notify (if any) answers. Sending ASCII AT text to the
// aa21/render chars is harmless (they fail to parse it). Listeners are already armed above.
const p: any = (session.right as any).peripheral;
const writables: any[] = [];
for (const s of (p?.services ?? [])) for (const ch of (s.characteristics ?? [])) {
  const props: string[] = ch.properties ?? [];
  if (props.includes("write") || props.includes("writeWithoutResponse")) writables.push(ch);
}
console.log(`\n[${ts()}] writable chars: ${writables.map((w) => w.uuid).join(", ")}`);
const pl = Buffer.from(cmd + term, "latin1");
for (const ch of writables) {
  const woResp = !(ch.properties ?? []).includes("write");   // prefer with-response if supported
  console.log(`\n[${ts()}] >>> ${ch.uuid} <- ${JSON.stringify(cmd)} (woResp=${woResp}) hex=${pl.toString("hex")}`);
  try { await ch.writeAsync(pl, woResp); } catch (e) { console.log("  write err", String(e)); }
  await new Promise((r) => setTimeout(r, 2000));   // watch for a reply on any notify
}
await new Promise((r) => setTimeout(r, 1500));

console.log(`[${ts()}] done (if no «...» lines appeared, the AT shell is on a different channel — see the GATT dump above).`);
await session.close();
process.exit(0);
