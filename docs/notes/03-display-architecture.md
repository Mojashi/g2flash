# 03 — Display architecture

Deep RE of the G2 mainapp (fw 2.2.4.34) display path, aimed at hot-loaded CFW
payloads that want to show custom content. Addresses are runtime Thumb pointers
(base `0x39E680`).

## Firmware = stock LVGL v9.3

The build is stock LVGL v9.3 (IAR), so RE = map known API → address. Confirmed
(fw 2.2.4.34):

| Symbol | Addr | Notes |
|--------|------|-------|
| `lv_image_create` | `0x4b0ee8` | |
| `lv_image_set_src` | `0x4b0f00` | `lv_image_t` has an **extra word** at obj+0x30 vs upstream: src@0x2c, w@0x3c, h@0x40, cf-bitfield@0x58 |
| `lv_label_create` / `lv_label_set_text` | `0x4b1c96` / `0x4b1cae` | |
| `lv_obj_create` | `0x43de22` | |
| `lv_obj_set_pos` / `set_size` | `0x43f03a` / `0x43f460` | |
| `lv_obj_invalidate` | `0x4405f6` | marks dirty only — safe from an RX context |
| `lv_obj_set_parent` | `0x44c880` | |
| `lv_display_get_default` | `0x44e94e` | |
| `_lv_display_refr_timer` | `0x452540` | |
| `lvgl_flush_cb` | `0x4716c4` | |
| `jbd_flush` | `0x588c90` | |

There is **no `lv_canvas` widget** compiled in — use `lv_image` for arbitrary
pixels.

## Display framework

- **Registry** `0x20066210` (16 B entries `{appID, dataCb, uiCb, cfg}`, count at
  `*0x20074410`, static init table `@0x6a6cc4` × 42).
- `display_startup(appID, data, len)` = `0x443904` posts `STARTUP` (cmd2) to the
  display queue; `ui_display_thread_handler` `0x442f00` →
  `dispatch_ui_event` `0x4419ce` → app `uiCb`.
- `page_manager` built a 576×288 root (child of the active screen) with two
  child containers: **base** = `mgr+0x1c` (opaque, visible) and **overlay** =
  `mgr+0x20` (transparent until activated); `mgr` at `*0x2007440c`.

### Front-layer window mechanism (`page_manager_register` `0x45f74c`)

`app_cfg_t.type` (`cfg[0xb]`) selects the layer:

- `type == 0` → parent the page root to **base** (opaque full-screen).
- `type != 0` → parent to **overlay** (transparent front layer) = a window/HUD
  on top of the current base app. For overlay pages `cfg.align` (`0x8`) sets the
  slide-in edge (0 = off-left, 1 = off-bottom, else off-top) — that is the
  native banner slide-in.

So to draw a front window from own-mode: set `cfg[0xb]=1`, make `cfg->root` an
opaque bordered `lv_obj` window, register the app entry as usual. (Own-mode
currently uses `cfg[0xb]=0` = base / full-screen.)

## Panel & per-frame path

- Panel = JBD micro-LED (jbd4010), 640×480 4bpp canvas at `*0x20074464`
  (= `0x20094400`, stride 320); only a 576×288 window is shown.
- The per-frame path is **not** `jbd_flush` — it is `lvgl_flush_cb` →
  `buffer_sync` `0x47163c` (px_map L8 → GPU/NemaGFX blit) → `FUN_00472036`
  async refresh.
- `jbd_flush(1)` `0x588c90` does a heavy panel init + MSPI powerup / refresh /
  powerdown on **each call**.
- Panel power runs via the `displaydrvmgr` task:
  `ASYNC_DISPLAY_DEVICE_POWER_UP/DOWN`. The display wakes on head-up (IMU
  `0x4bd5b6`) / wear / long-press-both-sides, and times out to idle (dashboard
  fade-out → panel powerdown).

## What WORKS (hardware-verified)

Verified via a self-built grayscale-QOI screenshot payload
([`patches/mode_screenshot.c`](../../patches/mode_screenshot.c) +
`demos/screenshot-rt.ts`, sid `0x7d`):

- **Raw-canvas write** (4bpp, `put_px`) + `*0x20074468 = 0` (skip the
  pre-compose clear) + `jbd_flush(1)` **from the BLE-RX context** (`on_data`).
  Draws box/text cleanly into the canvas; persists in SRAM when idle. Reliable
  **only when the display is idle**.
- Built `mode_boxtest` / `mode_text` (8×8 font [`patches/font8.h`](../../patches/font8.h),
  scale 3) — verified.

## What FAILS (reboots or invisible)

1. `jbd_flush` from the display-thread `uiCb` → re-enters jbd → **reboot**.
2. `_lv_display_refr_timer(0)` from `uiCb` → nested refr → **reboot**.
3. Rapid `jbd_flush(1)` > ~10 fps → **reboot** (MSPI power-cycle thrash);
   ≤ 10 fps survives but **flickers / blacks out** (power cycling).
4. Our top-layer `lv_label` → the firmware compositor does **not** render
   `lv_display`'s top layer → **invisible**.
5. Registering our app + `display_startup(unknownID)` while the dashboard is
   active → routed via the widget-transition path (`0x441d92`, appID hard-coded
   1/5/6/8/0xb) → our `uiCb` **not reliably dispatched**.
6. When **worn + compositor active**, the dashboard redraws every frame and
   overwrites raw-canvas writes ("gone in an instant").

## Key reframe

Do **not** overlay / fight the dashboard. Want a **separate self-controlled
full-screen mode** (like the EvenHub / terminal foreground apps that hide the
dashboard). The correct path is to become the foreground app so the compositor
renders *our* page — see [05 — CFW loader & modes](05-cfw-loader-and-modes.md).

## Screenshot debugger

`demos/screenshot-rt.ts <out>` triggers a payload's `'s'` capture on sid `0x7b`
and collects QOI on sid `0x7d` → PNG. The 4bpp canvas is reliable only when
idle; the **L8 drawbuf** (build `screenshot.c -DSS_FB_L8`, `*0x200745cc+0x10`,
576×288) is what the compositor renders to and is reliable when active. In some
tests both were black because the display was actually idle (wear-detect off + no
head-up).

## Stereo / per-lens note

Each lens is an independent MCU. A payload registered + entered runs on **both**,
but each free-runs its own frame counter → L/R desync (confirmed: L F:13364 vs
R F:13569). Because TX to the phone is gated to the R lens, all received frames
are tagged `arm=R` regardless of source — you **cannot** separate lenses by the
received arm; select the lens by the **trigger** arm instead. See
[04 — Two lenses & sync](04-two-lens-and-sync.md).
