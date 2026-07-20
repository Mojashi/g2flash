#!/usr/bin/env bun
// g2ctl — a small control/status CLI for the Even Realities G2 glasses, built on the
// reverse-engineered g2_setting protobuf service (sid 0x09) via g2-kit.
//
// Read-only (safe):
//   bun g2ctl.ts status            full device snapshot (battery, charge, FW, brightness,
//                                  head-up, wear, silent, display X/Y position, run state)
//   bun g2ctl.ts battery           battery % + charging state
//   bun g2ctl.ts watch [sec]       poll the snapshot every [sec] seconds (default 5)
//
// State-changing (reversible — just re-set):
//   bun g2ctl.ts brightness <lvl> [auto|manual]   set brightness level (+ auto on/off)
//   bun g2ctl.ts pos <x> <y>       set display position: X = horizontal, Y = vertical/height
//   bun g2ctl.ts posy <n>          set only Y (vertical position / perceived "focus" height)
//   bun g2ctl.ts posx <n>          set only X (horizontal position)
//   bun g2ctl.ts headup <angle> [on|off]          set head-up wake angle (+ switch)
//   bun g2ctl.ts wear <on|off>     wear detection
//   bun g2ctl.ts silent <on|off>   silent mode
//   bun g2ctl.ts hand <left|right> dominant hand
//
// The setters shift where the HUD sits in your view; values are device-defined levels —
// nudge in small steps. Everything is reversible by re-setting. NOTHING here resets,
// unpairs, or reflashes.
import {
  G2Session,
  querySettings,
  setBrightness,
  setXCoordinate,
  setYCoordinate,
  setHeadUp,
  setWearDetection,
  setSilentMode,
  setDominantHand,
  type DeviceSettingsSnapshot,
} from "g2-kit/ble";

function magic() { return (Math.floor(Math.random() * 250) + 1) & 0xff; }
const onoff = (s?: string) => (s === "on" || s === "1" || s === "true" ? 1 : 0);
function num(s: string | undefined, name: string): number {
  const n = Number(s);
  if (!Number.isFinite(n)) { console.error(`bad ${name}: ${s}`); process.exit(2); }
  return n;
}

const CHARGE = ["not charging", "charging", "full", "?"];
function printSnapshot(s: DeviceSettingsSnapshot) {
  console.log(
    `battery      : ${s.battery}%  (${CHARGE[s.chargingStatus] ?? `charge=${s.chargingStatus}`})\n` +
    `firmware     : L=${s.leftSoftwareVersion || "?"}  R=${s.rightSoftwareVersion || "?"}\n` +
    `brightness   : level=${s.autoBrightnessLevel}  auto=${s.autoBrightnessSwitchRestored ? "on" : "off"}\n` +
    `head-up      : ${s.headUpSwitchRestored ? "on" : "off"}  angle=${s.headUpAngleRestored}\n` +
    `display pos  : X=${s.xCoordinateLevelRestored}  Y=${s.yCoordinateLevelRestored}   (Y = vertical/height)\n` +
    `wear-detect  : ${s.wearDetectionSwitchRestored ? "on" : "off"}   silent: ${s.silentModeSwitchRestored ? "on" : "off"}\n` +
    `run-status   : ${s.deviceRunningStatus}   unread-msgs: ${s.unreadMessageCount}`,
  );
}

const [cmd = "status", a1, a2] = process.argv.slice(2);
const session = await G2Session.open({ quiet: true });
try {
  switch (cmd) {
    case "status": {
      const s = await querySettings(session, magic());
      if (!s) { console.error("no response"); break; }
      printSnapshot(s);
      break;
    }
    case "battery": {
      const s = await querySettings(session, magic());
      if (!s) { console.error("no response"); break; }
      console.log(`${s.battery}%  (${CHARGE[s.chargingStatus] ?? s.chargingStatus})`);
      break;
    }
    case "watch": {
      const sec = a1 ? num(a1, "sec") : 5;
      console.log(`polling every ${sec}s — Ctrl-C to stop`);
      for (;;) {
        const s = await querySettings(session, magic());
        const t = new Date().toISOString().split("T")[1]!.replace("Z", "");
        if (s) console.log(`[${t}] batt=${s.battery}% ${CHARGE[s.chargingStatus] ?? ""} | bright=${s.autoBrightnessLevel} | pos X=${s.xCoordinateLevelRestored} Y=${s.yCoordinateLevelRestored} | wear=${s.wearDetectionSwitchRestored} | run=${s.deviceRunningStatus}`);
        else console.log(`[${t}] (no response)`);
        await new Promise((r) => setTimeout(r, sec * 1000));
      }
    }
    case "brightness": {
      const lvl = num(a1, "level");
      const auto = a2 === "auto" ? 1 : a2 === "manual" ? 0 : undefined;
      const ok = await setBrightness(session, magic(), { brightnessLevel: lvl, ...(auto !== undefined ? { autoAdjust: auto } : {}) });
      console.log(ok ? `brightness -> ${lvl}${auto !== undefined ? ` (auto ${auto ? "on" : "off"})` : ""}` : "no ack");
      break;
    }
    case "pos": {
      const x = num(a1, "x"), y = num(a2, "y");
      const okx = await setXCoordinate(session, magic(), x);
      const oky = await setYCoordinate(session, magic(), y);
      console.log(`display pos -> X=${x} (${okx ? "ok" : "no ack"})  Y=${y} (${oky ? "ok" : "no ack"})`);
      break;
    }
    case "posx": { const x = num(a1, "x"); console.log((await setXCoordinate(session, magic(), x)) ? `X -> ${x}` : "no ack"); break; }
    case "posy": { const y = num(a1, "y"); console.log((await setYCoordinate(session, magic(), y)) ? `Y -> ${y}` : "no ack"); break; }
    case "headup": {
      const angle = num(a1, "angle");
      const sw = a2 !== undefined ? onoff(a2) : undefined;
      const ok = await setHeadUp(session, magic(), { headUpAngle: angle, ...(sw !== undefined ? { headUpSwitch: sw } : {}) });
      console.log(ok ? `head-up angle -> ${angle}${sw !== undefined ? ` (${sw ? "on" : "off"})` : ""}` : "no ack");
      break;
    }
    case "wear":   console.log((await setWearDetection(session, magic(), onoff(a1))) ? `wear -> ${onoff(a1)}` : "no ack"); break;
    case "silent": console.log((await setSilentMode(session, magic(), onoff(a1))) ? `silent -> ${onoff(a1)}` : "no ack"); break;
    case "hand":   console.log((await setDominantHand(session, magic(), a1 === "left" ? 0 : 1)) ? `hand -> ${a1}` : "no ack"); break;
    default:
      console.error(`unknown cmd '${cmd}'. try: status|battery|watch|brightness|pos|posx|posy|headup|wear|silent|hand`);
  }
} finally {
  await session.close();
}
process.exit(0);
