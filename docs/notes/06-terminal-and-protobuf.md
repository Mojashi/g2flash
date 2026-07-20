# 06 — Terminal protocol & protobuf

Reverse-engineering the G2 "terminal mode" (the on-lens AI-agent UI, BLE
protobuf on sid `0x30`) and the firmware's nanopb schema.

## Terminal mode hijack (solved)

An external BLE client (macOS, no phone / host app) can drive the on-lens agent
UI and render arbitrary agent text on the physical glasses. The full confirmed
solution — wire format, discriminant map, working sequence — is in
[`docs/terminal-protocol.md`](../terminal-protocol.md) (top "SOLVED" section).
Key facts:

- Outer frame = `field1 = DISCRIMINANT, field2 = magic, field(disc+2) = payload`.
- Sequence: `mode_sync(2)` → `host_status(2)` → `session_id_changed(id)` →
  `session_status(status=1,id)` → `agent_content(op=0,text)` renders text.
- Content-bind = event `0x13`, which fires **only** in `AGENT_PROCESSING`
  state 7.

### Method that cracked it

Built a **Unicorn emulator** of the real firmware to run firmware functions
against controllable SRAM. This resolved the `field1 = discriminant` truth that
hardware-only guessing couldn't (the emulator + reconstruction docs were
scratchpad-only, ephemeral).

## Protobuf schema recovery

The firmware uses **nanopb** (`pb_encode` / `pb_decode`, `<Msg>_tag` /
`which_<oneof>` idioms, IAR `s200_ap510b` build). Logging is deferred / ID-based
(`elog.async` / `clog.port`): the format-string bytes exist but are **not**
pointer-referenced in the image, so strings give names but are useless as xref
anchors.

**Structure** (100% from firmware): [`pb_extract.py`](../../pb_extract.py)
structurally scans app rodata (`0x438000..0x78f188`) for every `pb_msgdesc_t`,
parses each field, and resolves submessage links by transitive closure →
**244 messages / 856 fields / 34 roots** (16 oneof "envelope" protocols) →
[`docs/pb_schema.json`](../pb_schema.json) + [`docs/pb_schema.proto`](../pb_schema.proto).

**Names** (from the app side via Blutter): the Even app (`com.even.sg`) is
Flutter/Dart — protobuf lives in `libapp.so` (a ~40 MB Dart AOT snapshot),
**outside** the packed DEX (which is why a DEX grep failed). Running
[Blutter](https://github.com/worawit/blutter) reconstructs the Dart classes for
the exact VM version; each `<svc>.pb.dart` `BuilderInfo` yields name + tag + type
+ submsg per field. [`pb_blutter_extract.py`](../../pb_blutter_extract.py) parses
those → **26 services / 246 messages / 858 fields**;
[`pb_join.py`](../../pb_join.py) fingerprint-joins app messages to firmware
descriptors (child-field-count fingerprint + 1:1 assignment).

Confirmed firmware-addr → app-message bindings include: `0x777840` =
`TerminalDataPackage`, `0x7727a0` = `evenhub_main_msg_ctx`, `0x771300` =
`DashboardDataPackage`, `0x772398` = `EvenAIDataPackage` (100%), `0x777510` =
`TelepromptDataPackage`, `0x770d18` = `ConversateDataPackage`, `0x774af8` =
`navigation_main_msg_ctx`, `0x7761a8` = `QuicklistDataPackage`, `0x774c30` =
`NotificationDataPackage`, `0x777fc0` = `TranslateDataPackage`, `0x772980` =
`G2SettingPackage`, `0x771858` = `DashboardExtPackage`.

Deliverables: [`docs/pb_schema_named.proto`](../pb_schema_named.proto),
[`docs/pb_app_schema.json`](../pb_app_schema.json),
[`docs/pb_firmware_binding.md`](../pb_firmware_binding.md). For future app RE,
**Blutter on `libapp.so` is the method** (not DEX grep).

## `g2ctl` — settings CLI (HW-verified)

[`demos/g2ctl.ts`](../../demos/g2ctl.ts) wraps the `g2_setting` service
(**sid `0x09`**, `G2SettingPackage`) into a CLI. Reads
(`status/battery/watch`) and writes (`brightness/pos/posx/posy/headup/wear/
silent/hand`) both verified. Device snapshot fields: battery %, chargingStatus,
L/R FW, auto-brightness level + switch, head-up switch + angle, wear detection,
silent mode, `xCoordinateLevel` / `yCoordinateLevel` (display position; Y ≈
vertical focus), deviceRunningStatus, unreadMessageCount.

GATT map (from an `at-shell.ts` probe): the Even service `...2760...` block has 5
write/notify pairs — `0001/0002`, `5401/5402` (= `aa21` command), `6401/6402`
(= render, echoes writes), `7401/7402` (unknown); plus Nordic UART (a
log-**output** sink via `AT^LOGTYPE BLE`) and standard DIS `180a`. The `AT^`
shell is UART-input only — **not reachable over BLE**.

## IMU over BLE (measured)

[`demos/imu.ts`](../../demos/imu.ts). Path: you **must enter EvenHub mode first**
(sid `0xe0` `Cmd=0` CreateStartUpPageContainer + a ~3 s heartbeat `Cmd=12`) or
`OPEN_IMU` is silently ignored. Then send `Cmd=19` `APP_REQUEST_OPEN_IMU_PACKET`
with `ImuCtrl{IMUReportEn=1, reportFrq}`; the device acks `Cmd=20`, then streams
IMU data as async events.

- **Data:** x/y/z are wire-type 5 fixed32 = IEEE-754 **float32** (the proto says
  `uint32` but they are floats); `|vector| ≈ 1.0` ⇒ a normalized gravity/accel
  vector = head tilt/orientation, effectively continuous.
- **Only 3 axes over BLE.** Full 9-axis (ACC + GYR + MAG + Roll/Pitch/Yaw) is
  UART-only (`AT^IMU_RAWDATA` CSV). Widening the BLE packet needs CFW.
- **Rate:** `reportFrq` is the report *period* in ms; the floor is ~90 ms ⇒
  **max ~10–11 Hz** (`≤100` all clamp to ~90 ms; `200` → ~5 Hz; `1000` → 1 Hz).
  Good for head-gesture / orientation UI. Both arms relay the same event
  (dedupe by `arm == "R"`).

## Obtaining firmware images

The firmware download URL was captured via `adb logcat` on a non-rooted phone
while the app downloaded firmware (the APK is packed, so static grep fails). The
log line is `[EvenCore::EvenDioClient] Start download:
https://<cdn-host>/firmware/<md5>.bin`. 2.2.6.10 adds a bootloader component to
the OTA container (6 components), EvenHub **z-order** and **image compression**
(lz4/rle nav maps) — the Even Hub SDK 0.0.12 features. There is **no** delta /
differential firmware OTA and no image-delta transfer (image reflash is still
whole-image; the CFW `mode3/mode9` delta remains the only differential-image
path).
