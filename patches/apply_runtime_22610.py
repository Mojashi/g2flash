#!/usr/bin/env python3
"""
apply_runtime_22610.py — build the mode-runtime loader CFW image for the 2.2.6.10
firmware container. This is the 2.2.6.10 analogue of patch_compress.py (which is
2.2.4.34-specific); the two containers differ enough that patch_compress.py cannot
be reused as-is:

  * 2.2.6.10 has SIX components (an `ota/s200_bootloader.bin` OTA component was
    inserted before the main app), where 2.2.4.34 has five. The main app
    `ota/s200_firmware_ota.bin` is still the LAST component, so the append model
    (grow the last component, nothing downstream shifts) still holds.
  * Because the main app moved later in the file (comp_off 0x998e0 -> 0xbdde7),
    the file<->address mapping delta changed. This script does NOT rely on a hard
    coded DELTA for the main-app code; it derives comp_off from the container and
    keeps everything in a single consistent address space for the (PC-relative)
    hook encodings.

It performs exactly the runtime-loader wiring:
  (A) RX-intake redirect: rewrite the `bl` at the RX site to `bl rt_rx_hook`.
  (B) INPUT entry-detour:  rewrite the first 4 bytes of the input dispatcher to
      `b.w rt_input_tramp` (the trampoline replays the stolen prologue).
  (C) append the runtime blob (build.py on runtime_main.c) at the main-app payload
      tail and grow the component's size/offset metadata.

Checksums are fixed up in a SEPARATE step by `g2flash.py --recompute-checksums`
(the task's step 4), so this script leaves the component CRC32C + preamble CRC32
stale on purpose and does not touch them.

IMPORTANT — the hook encodings (bl / b.w) are PC-relative: the displacement is
(target - (site+4)), invariant under any uniform address-space shift, so they are
correct for on-device execution regardless of which base the disassembler used.
The runtime blob's INTERNAL absolute firmware-call addresses are NOT this script's
concern (they come from fw_2.2.6.10.h); see the build report / review notes.

Usage:
  python3 apply_runtime_22610.py <stock.bin> <out.bin>
then:
  python3 g2flash.py --recompute-checksums <out.bin>
"""
import sys, os, struct, json, subprocess

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# ---- main-app MRAM placement (mirrors g2flash.check_mainapp_fits_mram) ----
MAINAPP        = "ota/s200_firmware_ota.bin"
BOOTLOADER     = "ota/s200_bootloader.bin"
APP_LOAD_ADDR  = 0x00438000     # bootloader XIP-programs the main app here
APP_PREAMBLE   = 0x20           # it programs payload[0x20:], so payload[k] -> 0x438000 + k - 0x20
OTA_FLAG_ADDR  = 0x007FE000
MRAM_END       = 0x00800000
APP_MAX_END    = 0x007F0000     # conservative ceiling used by g2flash
BLOB_ALIGN     = 4              # 4-byte-align the appended blob (Thumb literal pools)

# ---- the two hook sites (fw_2.2.6.10.h). These are disassembler ("ghidra") thumb
# pointers; the corresponding stock file offset is ptr - GHIDRA_DELTA. ----
GHIDRA_DELTA   = 0x39E680        # file_off = thumb_ptr - GHIDRA_DELTA  (2.2.6.10 header convention)
HOOK_RX_SITE   = 0x0047ec27      # thumb ptr; even instr 0x47ec26, file off 0xE05A7
HOOK_RX_STOCK  = "e7f700ff"      # bl 0x466a2a (universal dispatcher)
HOOK_IN_SITE   = 0x0046728d      # thumb ptr; even instr 0x46728c, file off 0xC8C0D
HOOK_IN_STOCK  = "f8b58ab0"      # push {r3-r7,lr}; sub sp,#0x28

def mram_addr(payload_off):
    return APP_LOAD_ADDR + payload_off - APP_PREAMBLE

def align_up(x, a):
    return (x + a - 1) & ~(a - 1)

def hx(s):
    return bytes.fromhex(s.replace(" ", ""))

def _thumb_branch(pc, target, is_bl):
    """Encode a Thumb-2 32-bit BL (T1, is_bl=True) or B.W (T4, is_bl=False) from
    instruction address `pc` to `target`. Both are PC-relative to pc+4; the only
    encoding difference is hw2 bit12 (BL=1 / B.W=0)."""
    off = target - (pc + 4)
    assert off % 2 == 0, f"branch target {target:#x} not halfword-aligned from {pc:#x}"
    assert -(1 << 24) <= off < (1 << 24), f"branch {pc:#x}->{target:#x} out of +-16MB ({off:#x})"
    imm = (off >> 1) & 0xFFFFFF
    S     = (imm >> 23) & 1
    i1    = (imm >> 22) & 1
    i2    = (imm >> 21) & 1
    imm10 = (imm >> 11) & 0x3FF
    imm11 = imm & 0x7FF
    j1 = (~(i1 ^ S)) & 1
    j2 = (~(i2 ^ S)) & 1
    hw1 = 0xF000 | (S << 10) | imm10
    hw2 = (0xD000 if is_bl else 0x9000) | (j1 << 13) | (j2 << 11) | imm11
    return bytes([hw1 & 0xFF, hw1 >> 8, hw2 & 0xFF, hw2 >> 8])

def enc_bl(pc, target): return _thumb_branch(pc, target, True)
def enc_bw(pc, target): return _thumb_branch(pc, target, False)

def parse_components(img):
    n = struct.unpack_from('<I', img, 8)[0]
    comps = []
    for i in range(n):
        eid, off, size, crc = struct.unpack_from('<IIII', img, 0x40 + i * 16)
        ps = struct.unpack_from('<I', img, off + 8)[0]
        name = bytes(img[off + 48:off + 128]).split(b'\0')[0].decode('latin1')
        comps.append(dict(i=i, eid=eid, off=off, size=size, crc=crc, ps=ps, name=name,
                          payload_end=off + 128 + ps))
    return n, comps

def build_blob():
    """Compile patches/runtime_main.c via build.py --json -> {text, functions}. The
    blob is position-independent (build.py resolves intra-.text branches and the
    PC-relative -fropi refs), so no placement base is passed."""
    cmd = ["python3", os.path.join(SCRIPT_DIR, "build.py"),
           os.path.join(SCRIPT_DIR, "runtime_main.c"), "--json"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"build.py failed:\n{r.stderr or r.stdout}")
    return json.loads(r.stdout)

def fn_off(blob, name):
    for f in blob["functions"]:
        if f["name"] == name:
            return f["offset"]
    raise SystemExit(f"runtime blob: function {name!r} not found")

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "g2_2.2.6.10.bin"
    dst = sys.argv[2] if len(sys.argv) > 2 else "g2_2.2.6.10_cfw.bin"
    img = open(src, "rb").read()
    data = bytearray(img)

    n, comps = parse_components(img)
    print(f"container: {n} components")
    for c in comps:
        print(f"  [{c['i']}] {c['name']:30s} off=0x{c['off']:x} ps=0x{c['ps']:x} end=0x{c['payload_end']:x}")

    app = next((c for c in comps if c['name'].endswith(MAINAPP)), None)
    if app is None:
        raise SystemExit(f"main-app component {MAINAPP} not found")
    if app['payload_end'] != len(img):
        raise SystemExit(f"main-app payload ends at 0x{app['payload_end']:x} but file is "
                         f"0x{len(img):x}; append model requires it to be the last component")
    idx, comp_off, old_ps = app['i'], app['off'], app['ps']

    # geometry: file_off <-> ghidra addr (header convention) and <-> true MRAM exec addr
    payload0 = comp_off + 128
    # ghidra even addr E maps to file E - (GHIDRA_DELTA-1); we keep hook math in ghidra space.
    def file_to_ghidra_even(foff):   # inverse of (ghidra_even - (GHIDRA_DELTA-1))
        return foff + (GHIDRA_DELTA - 1)

    # ---- verify the two hook sites' stock bytes ----
    site_a_file = HOOK_RX_SITE - GHIDRA_DELTA
    site_b_file = HOOK_IN_SITE - GHIDRA_DELTA
    for foff, stock, label in [(site_a_file, HOOK_RX_STOCK, "RX site A"),
                               (site_b_file, HOOK_IN_STOCK, "INPUT site B")]:
        cur = bytes(data[foff:foff + 4]).hex()
        if cur != stock:
            raise SystemExit(f"{label} @ file 0x{foff:x}: expected {stock} got {cur} "
                             "(not the stock 2.2.6.10 base?)")
        print(f"  {label}: file 0x{foff:x} stock {cur} OK")

    # ---- compile + place the runtime blob at the main-app payload tail ----
    blob_j = build_blob()
    blob = bytes.fromhex(blob_j["text"])
    blob_off  = align_up(old_ps, BLOB_ALIGN)          # offset within main-app payload
    pad       = blob_off - old_ps
    blob_file = payload0 + blob_off                   # file offset of blob byte 0
    assert blob_file == len(img) + pad, "blob must append at (aligned) EOF"
    blob_mram   = mram_addr(blob_off)                 # true on-device exec address
    blob_ghidra = file_to_ghidra_even(blob_file)      # disassembler-space address (even)
    rx_off   = fn_off(blob_j, "rt_rx_hook")
    tramp_off= fn_off(blob_j, "rt_input_tramp")
    if rx_off != 0:
        raise SystemExit(f"rt_rx_hook must be at blob offset 0, got 0x{rx_off:x}")
    rx_ghidra    = blob_ghidra + rx_off
    tramp_ghidra = blob_ghidra + tramp_off
    print(f"\nblob: {len(blob)} B, place @ payload+0x{blob_off:x} "
          f"(file 0x{blob_file:x}, MRAM 0x{blob_mram:08x}, ghidra 0x{blob_ghidra:08x})")
    print(f"  rt_rx_hook     blob+0x{rx_off:x}    -> ghidra 0x{rx_ghidra:08x} (MRAM 0x{mram_addr(blob_off+rx_off):08x})")
    print(f"  rt_input_tramp blob+0x{tramp_off:x} -> ghidra 0x{tramp_ghidra:08x} (MRAM 0x{mram_addr(blob_off+tramp_off):08x})")

    # ---- MRAM ceiling ----
    new_ps   = blob_off + len(blob)
    prog_end = mram_addr(new_ps)
    if prog_end > APP_MAX_END:
        raise SystemExit(f"too large: prog_end 0x{prog_end:08x} > ceiling 0x{APP_MAX_END:08x}")
    print(f"  new_ps=0x{new_ps:x}  prog_end=0x{prog_end:08x}  "
          f"({(APP_MAX_END - prog_end)//1024} KB under 0x{APP_MAX_END:08x})")

    # ---- compute hook bytes (PC-relative, in ghidra space) ----
    a_site_ghidra = file_to_ghidra_even(site_a_file)  # 0x47ec26
    b_site_ghidra = file_to_ghidra_even(site_b_file)  # 0x46728c
    a_new = enc_bl(a_site_ghidra, rx_ghidra)
    b_new = enc_bw(b_site_ghidra, tramp_ghidra)
    print(f"\nhook A: file 0x{site_a_file:x} {HOOK_RX_STOCK} -> {a_new.hex()} "
          f"(bl 0x{a_site_ghidra:x}->0x{rx_ghidra:x})")
    print(f"hook B: file 0x{site_b_file:x} {HOOK_IN_STOCK} -> {b_new.hex()} "
          f"(b.w 0x{b_site_ghidra:x}->0x{tramp_ghidra:x})")

    # ---- apply: 2 hooks, append blob, grow metadata (NOT checksums) ----
    data[site_a_file:site_a_file + 4] = a_new
    data[site_b_file:site_b_file + 4] = b_new
    append = bytearray(pad) + blob                    # pad (0 here, old_ps 4-aligned) + blob
    assert len(data) + pad == blob_file
    data.extend(append)

    struct.pack_into('<I', data, comp_off + 8, new_ps)                 # subheader ps
    struct.pack_into('<I', data, 0x40 + idx * 16 + 8, new_ps + 128)    # TOC entry size
    pre0 = struct.unpack_from('<I', data, comp_off + 128)[0]           # main-app preamble len (low24)
    struct.pack_into('<I', data, comp_off + 128,
                     (pre0 & 0xff000000) | (new_ps & 0xffffff))
    print(f"\ngrew main-app: ps 0x{old_ps:x}->0x{new_ps:x}, TOC size ->0x{new_ps+128:x}, "
          f"preamble len ->0x{new_ps & 0xffffff:x}")
    print("  (component CRC32C + preamble CRC32 left stale — run g2flash.py --recompute-checksums)")

    open(dst, "wb").write(data)
    print(f"\nwrote {dst} ({len(data)} bytes)")

    # emit a machine-readable manifest for the verifier / report
    manifest = {
        "src": os.path.basename(src), "dst": os.path.basename(dst),
        "src_len": len(img), "dst_len": len(data),
        "comp_off": comp_off, "idx": idx, "old_ps": old_ps, "new_ps": new_ps,
        "blob_len": len(blob), "blob_off": blob_off, "blob_file": blob_file,
        "blob_mram": blob_mram, "blob_ghidra": blob_ghidra,
        "prog_end": prog_end,
        "hook_a": {"file": site_a_file, "old": HOOK_RX_STOCK, "new": a_new.hex(),
                   "site_ghidra": a_site_ghidra, "target_ghidra": rx_ghidra},
        "hook_b": {"file": site_b_file, "old": HOOK_IN_STOCK, "new": b_new.hex(),
                   "site_ghidra": b_site_ghidra, "target_ghidra": tramp_ghidra},
        "meta_edits": {
            "subheader_ps_off": comp_off + 8,
            "toc_size_off": 0x40 + idx * 16 + 8,
            "preamble_len_off": comp_off + 128,
        },
    }
    with open(os.path.join(SCRIPT_DIR, "runtime_22610_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print("wrote patches/runtime_22610_manifest.json")

if __name__ == "__main__":
    main()
