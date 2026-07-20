# g2 CFW demos

Two small [Bun](https://bun.sh) programs that talk to a pair of Even Realities
G2 glasses over Bluetooth and show off the [custom firmware](../) built by
`../build_cfw.sh`:

- **`detect-cfw.ts`** — reads the glasses' settings and reports whether they're
  running the custom firmware, and which extensions it advertises. Works on
  stock firmware too (it just reports "no CFW").
- **`video-bench.ts`** — streams a video (as a GIF) to the lens as fast as it
  acks and benchmarks the achieved framerate / byte count. Streams via the
  CFW's compressed display modes — 8bpp full frames, 8bpp XOR deltas, or 4bpp
  indexed BMP — selectable with `G2_MODE` to compare size and throughput.
- **`stereo-demo.ts`** — an animated **stereoscopic 3D** demo. Renders a
  separate left-eye and right-eye view of a moving 3D scene with real binocular
  disparity and streams the pair with the CFW's **per-lens stereo** path (image
  mode 4), so each lens shows its own eye's image and the scene appears to have
  depth. Three scenes (`cube`, `rings`, `rds`) and a glasses-free preview mode.

They depend on [`g2-kit`](https://github.com/jimrandomh/g2-kit-unofficial) (a
reverse-engineered BLE library for the G2), pulled directly from GitHub — see
`package.json`. Nothing here needs the rest of this repo at runtime; the CFW
just needs to already be flashed for the demos to show anything interesting.

## Setup

```bash
cd demos
bun install
```

> The glasses must be powered on and **not** connected to the phone (quit the
> Even app / turn off the phone's Bluetooth) so they advertise for a direct
> connection. On macOS the first run prompts for Bluetooth permission.

## Detect the firmware

```bash
bun detect-cfw.ts        # or: bun run detect
```

On the custom firmware you'll see something like:

```
firmware: L=2.2.4.34 R=2.2.4.34
CFW detected: EVENCFW/1 img576 imgz xordelta stereo
  contract v1, features: img576, imgz, xordelta, stereo
  img576=yes imgz=yes xordelta=yes stereo=yes
```

On stock firmware it prints `no CFW capability field`.

## Video streaming benchmark

`video-bench.ts` takes a GIF and streams its frames. Make one from any video
with ffmpeg (grayscale, sized to the lens):

```bash
ffmpeg -i input.mp4 -vf "fps=30,scale=288:144:flags=area,format=gray" demo.gif
bun video-bench.ts demo.gif        # or: bun run bench demo.gif
```

It decodes/rescales/compresses every frame up front, then streams them in
order, pacing on the per-fragment acks, and prints framerate + bytes at the end.

Useful environment variables:

| Var | Default | Meaning |
|-----|---------|---------|
| `G2_IMG_W` / `G2_IMG_H` | `288` / `144` | target size (max `576`×`288`) |
| `G2_IMG_THRESHOLD` | `-1` | `>=0` = 1-bit threshold; `-1` = grayscale |
| `G2_MODE` | `full` | `full` = 8bpp full frame (mode 2); `delta` = 4bpp bounding-box update of the changed region (mode 3); `bmp` = 4bpp BMP via stock loader (mode 1); `raw4` = headerless 4bpp via fast expander (mode 6) |
| `G2_KEYFRAME_INTERVAL` | `0` | in `delta` mode, force a full frame every N |
| `G2_FRAME_STRIDE` | `1` | use every Nth source frame |
| `G2_MAX_FRAMES` | `0` | cap frame count (`0` = all) |
| `G2_WINDOW` | `2` | image messages in flight at once (`1` = serial) |
| `G2_DRY_RUN` | — | `1` = decode/compress/report only, don't connect |

Sweep `G2_WINDOW` (e.g. `1`, `2`, `4`) to see how much the ack round-trip is
costing — higher windows overlap the next frame's BLE transfer with the current
frame's on-device processing. Typical results on the CFW: ~22 fps at 288×144,
~9 fps at 576×288.

## Stereoscopic 3D

`stereo-demo.ts` shows off the CFW's per-lens stereo path. Every frame is a
`[0x04][zlib(leftEye ++ rightEye)]` message (image mode 4): two 8bpp frames in
one payload, sent to one arm. The firmware's cross-lens completion sync runs the
decoder on both lenses and each keeps only its half — so the **left lens** draws
the left-eye view and the **right lens** the right-eye view. The two views differ
by a small horizontal disparity, and the brain fuses them into depth.

```bash
bun stereo-demo.ts                 # or: bun run stereo   (rotating wireframe cube)
G2_SCENE=rings bun stereo-demo.ts  # flying through a tunnel of rings
G2_SCENE=rds   bun stereo-demo.ts  # random-dot stereogram (a shape floats out of noise)
```

The demo first reads the glasses' capabilities and refuses to run unless the
`stereo` feature is advertised (see `detect-cfw.ts`).

**No glasses handy?** Render a preview instead of streaming — no BLE needed:

```bash
G2_DRY_RUN=1 bun stereo-demo.ts    # writes stereo-preview-<scene>-{sbs,anaglyph}.bmp
```

`…-sbs.bmp` is the left|right pair side by side (free-view by crossing or
relaxing your eyes); `…-anaglyph.bmp` is a red/cyan composite for red-left /
cyan-right glasses. The dry run also prints the disparity band and the
compressed message size so you can gauge fusibility and throughput.

The stereo geometry: two virtual cameras an interocular distance apart, both
looking down +Z, with the images converged so a chosen depth `Zc` has zero
disparity. Points nearer than `Zc` get **crossed** disparity and pop out of the
display; points farther get **uncrossed** disparity and sit behind it. Keep the
magnitude to a handful of pixels or the eyes can't fuse — the defaults stay
within roughly ±9 px on the 288×144 panel.

Useful environment variables:

| Var | Default | Meaning |
|-----|---------|---------|
| `G2_SCENE` | `cube` | `cube` (wireframe cube), `rings` (tunnel), `rds` (random-dot stereogram) |
| `G2_IMG_W` / `G2_IMG_H` | `288` / `144` | per-lens image size (max `576`×`288`) |
| `G2_FRAMES` | `600` | frames to render/stream (the animation loops over this) |
| `G2_FPS` | `0` | pace to this framerate (`0` = as fast as acks allow) |
| `G2_IOD` | `0.4` | interocular distance in world units — the disparity scale |
| `G2_FOCAL` | `210` | focal length in px |
| `G2_CONVERGE` | `5.5` | convergence depth `Zc` (the zero-disparity plane) |
| `G2_WINDOW` | `2` | image messages in flight at once (backpressure) |
| `G2_DRY_RUN` | — | `1` = write a preview BMP and exit, don't connect |
| `G2_PREVIEW_FRAME` | `30` | which frame index the preview captures |

Per-frame message size (288×144, compressed): ~5 KB for `cube`, ~13–14 KB for
`rings`/`rds`. The wireframe scenes are mostly black so they compress hard and
stream at several fps; the random-dot field is near-incompressible and slower.
Drop `G2_IMG_W`/`G2_IMG_H` (e.g. `192`×`96`) for smoother motion.

## Requires the custom firmware

`video-bench.ts` and `stereo-demo.ts` use display modes that only exist in the
CFW; against stock firmware they won't render. Build and flash the firmware
first (see the [top-level README](../README.md)), then confirm with
`detect-cfw.ts`.
