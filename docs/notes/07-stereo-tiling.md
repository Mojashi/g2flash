# 07 — Full-panel stereo tiling

Getting a full-panel (576×288) stereoscopic 3D view onto the real glasses via
the **image `mode-4`** path (before the on-device 3D renderer of
[05 — CFW loader & modes](05-cfw-loader-and-modes.md) existed).

`mode-4` payload = `[0x04][zlib(left w*h ++ right w*h)]`; each lens uses
`FW_SIDE` to take its own half. Demo: `demos/stereo-demo.ts`.

## Failure → fix (in the order they were hit)

1. **A single 576 container reboots instantly.** The 576 patch only relaxes the
   *size check*; the display buffer stays 288×144, so a full-screen 8bpp write
   overflows → hardfault. → **Tiling (2×2 of 288×144) is mandatory.** A single
   tile > 288×144 is not allowed.
2. **A 5-container CREATE never acks.** Registering image tiles in the CREATE's
   `extraContainerNames` gets the multi-container CREATE rejected. → **CREATE
   only the root StartUpPage; declare all tiles in one `Cmd=7` REBUILD**
   (`buildImageContainers`, same as g2-kit's `G2ImageStreamer`). Per-tile
   REBUILDs overwrite each other — batch them into one frame.
3. **Mid-frame `NO_ACK` abort.** The firmware sometimes doesn't return the
   `Cmd=3` ack even though it drew. → **Tolerate missing acks** (slide up to ~8
   in a row) and shorten the fragment ack timeout (12 s → 2.5 s).
4. **A still frame shows nothing.** Ending the stream with `buildShutDown` closes
   the container and the image disappears. → **HOLD mode** (keep resending the
   final frame, never shut down). Also, a new container's **first `Cmd=3` is
   silently dropped** → a warmup frame is required.
5. **Only one eye renders.** `mode-4` sends both halves in one zlib blob; the L
   lens decodes only the first half, the R lens decompresses all and takes the
   second. A dropped tail fragment leaves L recoverable but R failing. Happened
   at `window=4`. → **`window=1` (serial)** for guaranteed fragment delivery.
6. **The payload is huge and zlib doesn't help.** Anti-aliased (Wu) lines create
   continuous grey gradients along edges, a different value every pixel, so zlib
   can't run. → **AA off (hard single-value lines)** → mostly-black with runs of
   digits → 58 KB → 14 KB (~4×), halving the fragment count.
7. **★ Fatal: L and R drift within the same tile** (fusion breaks when moving).
   Cross-lens sync pairs L/R **per message**; the L lens draws one beat after R
   via the sync path. With 1 container = 1 msg/frame, L keeps up (drift ≈ 1
   frame, tolerable). With 4 containers = 4 msg/frame, **the L lens's draw queue
   backs up** → R = latest, L = several frames behind → fatal drift. → **`window=1`
   + a low frame rate (`G2_FPS ≈ 0.5`)** so the flow drops to ~1 container's
   worth and the L lens can draw all 4 tiles every frame. **Sending to both arms
   separately is wrong** (BLE arrival skews and worsens desync — always leave
   sync to the glasses' cross-lens mechanism).

## Working configuration

```
G2_SCENE=map G2_AA=0 G2_IMG_W=576 G2_IMG_H=288 G2_TILED=1 G2_WINDOW=1 G2_FPS=0.5
```

(+ CREATE root only → one batched REBUILD, warmup frame, ack tolerance; for a
still frame fix `G2_MAP_AZ` and set `G2_HOLD`.) Result: full-panel stereo fuses
perfectly, but at **~0.5 fps** — rate-limited by 4 tiles × 2 fragments = 8 serial
messages plus the L lens's per-frame draw budget.

## The real speed fix

Either add a firmware **present barrier** (present all 4 containers at once), or
do **on-device 3D rendering** (send the model once + pose/IMU, draw both eyes
atomically). The latter is what [05 — CFW loader & modes](05-cfw-loader-and-modes.md)
`mode_ownanim` became. The render request spec is
[`docs/onboard-3d-render-request.md`](../onboard-3d-render-request.md); real map
data comes from `demos/fetch-city.ts` (OSM Overpass → `demos/city.json`).
