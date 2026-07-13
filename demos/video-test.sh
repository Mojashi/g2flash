#!/bin/bash
export G2_IMG_W=576
export G2_IMG_H=288
export G2_IMG_THRESHOLD=128
export G2_MODE=delta
#export G2_WINDOW=1
#export G2_FRAME_SLEEP=100
#bun video-bench.ts bad_apple_quarter.gif

export G2_WINDOW=2
export G2_FRAME_SLEEP=0
bun video-bench.ts bad_apple_fullscreen.gif
