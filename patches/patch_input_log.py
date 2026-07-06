#!/usr/bin/env python3
"""
patch_input_log.py — TEMPORARY diagnostic overlay (remove after gesture mapping).

Layers ONE hook on top of the CFW image so we can observe how physical ring/
touch gestures map to the firmware's internal input SUBTYPE (the value r7 in
FUN_004424a2). We redirect the single `bl FUN_004424a2` @0x004436c8 (the
msg-type==7 input-event case in the display-thread loop FUN_00442f00) to an
injected `log_input()` (patches/log_input.c) that dumps the raw event record via
the compact EasyLogger, then tail-calls the real dispatcher. Behavior is
otherwise unchanged.

The stub lives in the free gap between the zlib glue (ends 0x491972) and the
settings wrapper (0x491ab0) inside the reclaimed dead region — so it does not
disturb any of patch_compress.py's blobs. Runs on the CFW image (Faceclaw needs
the CFW) and re-fixes the component checksums.

    python3 patch_input_log.py [in=g2_2.2.4.34_cfw.bin] [out=g2_2.2.4.34_cfw_evtlog.bin]

After flashing, exercise each gesture in EvenHub/Faceclaw, pull the compress_log
(EFS), and decode with the *patched* image so the custom format string resolves:

    firmware/decode_compress_log.py --fw g2flash/g2_2.2.4.34_cfw_evtlog.bin <log>.bin | grep FCEVTLOG
"""
import os, sys

# reuse the harness (same dir): BL encoder, blob builder, checksum fixup, mapping
from patch_compress import enc_bl, build_blob, _fn, fixup_checksums, g2f, hx

# --- placement (ghidra addresses) -------------------------------------------
LOGHOOK_ADDR = 0x491980           # in the glue(0x491972)->settings(0x491ab0) gap
LOGHOOK_CAP  = 0x491ab0 - LOGHOOK_ADDR   # 0x130 = 304 B (must not reach settings_send_wrapper)
CALL_SITE    = 0x004436c8         # `bl FUN_004424a2` in FUN_00442f00 (msg type 7)
DISPATCHER   = 0x004424a2         # FUN_004424a2

FMT = b"FCEVTLOG f0=%x sub=%x f2=%x\x00"


def make_patch():
    # 2-pass build so the format string's absolute address is a link-time-free
    # constant: pass 1 to size the code, then place the string right after it and
    # rebuild with -DFMT_ADDR. The pass-1 placeholder must be a real in-range
    # 32-bit address (not 0) so it already compiles to movw/movt — otherwise the
    # compiler folds 0 into a short `movs` and the code length shifts in pass 2.
    p1 = build_blob("log_input.c", [f"-DFMT_ADDR=0x{LOGHOOK_ADDR:x}"])
    code_len = p1["text_len"]
    fmt_addr = LOGHOOK_ADDR + code_len
    p2 = build_blob("log_input.c", [f"-DFMT_ADDR=0x{fmt_addr:x}"])
    code = bytes.fromhex(p2["text"])
    assert len(code) == code_len, f"code size drifted between passes ({code_len} -> {len(code)})"
    assert _fn(p2, "log_input")["offset"] == 0, "log_input must be first in .text"

    blob = code + FMT
    end = LOGHOOK_ADDR + len(blob)
    assert len(blob) <= LOGHOOK_CAP, (
        f"log_input blob is {len(blob)} B but the gap at {LOGHOOK_ADDR:#x} holds only "
        f"{LOGHOOK_CAP} B (ends {end:#x}, settings_send_wrapper starts 0x491ab0)")
    print(f"  layout: log_input {LOGHOOK_ADDR:#x} + {len(blob)} B "
          f"(code {code_len} + fmt {len(FMT)}) -> {end:#x};  fmt@{fmt_addr:#x}")

    orig_bl = enc_bl(CALL_SITE, DISPATCHER)   # the stock `bl FUN_004424a2` we expect
    new_bl  = enc_bl(CALL_SITE, LOGHOOK_ADDR)
    return [
        # inject the logger stub into the dead-region gap (overwrites dead firmware)
        (g2f(LOGHOOK_ADDR), None, blob.hex(), "log_input() diagnostic stub"),
        # redirect the input-event dispatch call through it
        (g2f(CALL_SITE), orig_bl, new_bl, "bl log_input (was bl FUN_004424a2)"),
    ]


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)   # g2flash/
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(root, "g2_2.2.4.34_cfw.bin")
    dst = sys.argv[2] if len(sys.argv) > 2 else os.path.join(root, "g2_2.2.4.34_cfw_evtlog.bin")

    print("compiling diagnostic stub (build.py):")
    patches = make_patch()
    data = bytearray(open(src, "rb").read())
    for off, orig, new, desc in patches:
        n = hx(new)
        if bytes(data[off:off + len(n)]) == n:
            print(f"  {off:#x}: already patched ({desc})")
            continue
        if orig is not None:                       # bl site: verify stock bytes first
            o = hx(orig)
            cur = bytes(data[off:off + len(o)])
            assert cur == o, f"{off:#x} ({desc}): expected {o.hex()} got {cur.hex()}"
        data[off:off + len(n)] = n
        print(f"  {off:#x}: {desc} ({len(n)} B)")
    print("recomputing checksums:")
    fixup_checksums(data)
    open(dst, "wb").write(data)
    print(f"wrote {dst} ({len(data)} bytes)")


if __name__ == "__main__":
    main()
