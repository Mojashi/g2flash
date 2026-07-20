# 01 — Hardware & dev facts

High-level facts about the Even G2 as a development target.

## Panel & display

- **576×288 px, single-color green, 16 grey levels.** The physical panel is a
  JBD micro-LED (jbd4010 driver) with a 640×480 4bpp canvas (stride 320) but
  only a 576×288 window is shown.
- The two arms (lenses) are **independent BLE peripherals**, advertised as
  `Even G2_..._L_xxxxxx` and `Even G2_..._R_xxxxxx` (the suffix is the last
  three MAC bytes). Each arm is a separate **Apollo510 MCU**.
- **Input events (tap / swipe / wear-detect) fire on the RIGHT arm only.** The
  R lens is the "transmit lens" connected to the phone; see
  [04 — Two lenses & sync](04-two-lens-and-sync.md).

## Stock display path limits

- The **official Even Hub SDK** is a WebView app with a proportional font
  (~50 cols × 10 rows measured) — unusable for a real terminal. Its image
  container has **no full-screen path** (stock caps at 288×144).
- The stock firmware is **exclusive with the Even app**: only one host can be
  connected at a time. Reconnecting the official app upgrades firmware and wipes
  any CFW (this is the clean uninstall path).

## What needs CFW

Font freedom, full-screen 576×288 single-shot transfer, per-lens stereo pairs,
and compressed / delta transfer all require custom firmware. Rough throughput
with the image CFW: **~22 fps @ 288×144, ~9 fps @ 576×288**.

## Library landscape (direct BLE, no phone)

- **[jimrandomh/g2-kit-unofficial](https://github.com/jimrandomh/g2-kit-unofficial)**
  (Bun/TS, MIT) is the best direct-BLE library. Protocol docs live under its
  `ble/docs/`. Practical constraints it documents:
  - Container names ≤ 14 chars.
  - `CREATE` only acks on the first call.
  - First-stream-dropped bug → send one **warmup** frame that you discard.
  - A **heartbeat every ~5 s** is required to keep the session alive.
  - `Cmd=3` image fragments ≤ 4 KB.
  - Its `lc3-decoder` `dlopen`s at import; on a box without `liblc3` you must
    patch around it.
- **Fonts:** GNU **Unifont** JP (`.hex` format) is ideal — 16 B/glyph halfwidth,
  32 B fullwidth, matches `wcwidth`, ~59k glyphs including Japanese, ~30-line
  parser.
- Other references:
  [nickustinov/even-g2-notes](https://github.com/nickustinov/even-g2-notes),
  MentraOS `G2.kt` (Android/iOS native SDK),
  [jimrandomh/faceclaw](https://github.com/jimrandomh/faceclaw),
  [droidbridge](https://github.com/Commute773/droidbridge) (turn an Android
  phone into a BLE proxy — structurally solves the zombie/stale-handle problem).

## Protocol gotchas (verified on-device)

- g2-kit's `docs/*.md` are partly stale; the **generated protos +
  `envelope.ts` / `ble.ts` / `messages.ts` are authoritative**: 8-byte header,
  CRC only on the final fragment of a concatenated protobuf, `flag REQUEST=0x20`,
  chunk size 232.
- EvenHub audio is `Cmd=15/16` (docs saying 18/19 are wrong). `Cmd=19/20` =
  IMU open — see [06 — Terminal & protobuf](06-terminal-and-protobuf.md).
