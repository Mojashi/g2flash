#!/usr/bin/env python3
"""
Build the mode-runtime LOADER CFW image for g2_2.2.4.34.

This is a deliberately MINIMAL CFW: the stock image plus (1) the loader code blob
(runtime_main_22434.c) appended to the tail of the main-app payload, and (2) exactly
ONE in-place edit — the RX-site `bl FUN_00441c68` at 0x0045aaa4 (the universal inbound
aa21-frame service dispatcher call) redirected to rt_rx_hook. rt_rx_hook handles the
loader's private RUNTIME_SID (0x7b) commands, then tail-calls the real dispatcher so
every other sid is byte-for-byte unchanged and the stock RX wrapper still frees the
payload (AAPCS preserves r4). This is the SAME site + idiom the screenshot CFW's
cap_rx_hook proved safe.

WHY THIS IS THE SAFE BASE (2.2.4.34, single app code component):
  - The ONLY brick-critical operation is the container assembly, and this script reuses
    patch_compress.py's proven fixup order verbatim: append -> fix subheader ps, TOC
    entry size (ps+128), main-app preamble length (low 24 bits — what the bootloader
    actually programs to MRAM) -> recompute preamble crc32 then component crc32c (TOC +
    subheader echo). The main app is the LAST component, so appending shifts nothing.
  - Everything the loader does at RUNTIME is recoverable: a bad payload / cache / anchor
    at worst hard-faults into a watchdog reset back into this same valid CFW. The loader
    is DORMANT unless a frame arrives on sid 0x7b, so the glasses boot + behave stock and
    OTA re-flash is always reachable.
  - A hard MRAM-ceiling check (duplicate of g2flash.check_mainapp_fits_mram) refuses an
    oversized image.

Output: g2_2.2.4.34_loader.bin (default), plus the clang-free op list is proven to
reproduce the compiled image byte-for-byte (same guarantee as patch_compress.py).
"""
import sys, os, struct, zlib, json, subprocess

DELTA = 0x39E680  # file_off = ghidra_addr - DELTA (single OTA mainApp component on 2.2.4.34)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

def g2f(addr):
    return addr - DELTA

# ---- main-app MRAM placement (mirrors g2flash.py check_mainapp_fits_mram) ----
MAINAPP       = "ota/s200_firmware_ota.bin"
APP_LOAD_ADDR = 0x00438000   # bootloader XIP-programs the main app here
APP_PREAMBLE  = 0x20         # it programs payload[0x20:], so payload[k] -> 0x438000 + k - 0x20
OTA_FLAG_ADDR = 0x007FE000   # OTA magic word (last 8 KB of MRAM)
MRAM_END      = 0x00800000
APP_MAX_END   = 0x007F0000   # conservative ceiling: leave the top ~56 KB for NV + flag
BLOB_ALIGN    = 4            # 4-byte-align the appended blob (Thumb literal pools)

# ---- the single RX-hook redirect site (verified by disassembly; identical to the
#      screenshot CFW's CAP_RX_SITE). Stock bytes = `bl 0x441c68`. ----
RX_HOOK_SITE  = (0x0045aaa4, "e7 f7 e0 f8")

def mram_addr(payload_off):
    return APP_LOAD_ADDR + payload_off - APP_PREAMBLE

def align_up(x, a):
    return (x + a - 1) & ~(a - 1)

def enc_bl(pc, target):
    """Encode a Thumb-2 BL (T1) from instruction address `pc` to `target`."""
    off = target - (pc + 4)
    assert off % 2 == 0, f"BL target {target:#x} not halfword-aligned from {pc:#x}"
    assert -(1 << 24) <= off < (1 << 24), f"BL {pc:#x}->{target:#x} out of +-16MB range"
    imm = (off >> 1) & 0xFFFFFF
    S = (imm >> 23) & 1
    i1 = (imm >> 22) & 1
    i2 = (imm >> 21) & 1
    imm10 = (imm >> 11) & 0x3FF
    imm11 = imm & 0x7FF
    j1 = (~(i1 ^ S)) & 1
    j2 = (~(i2 ^ S)) & 1
    hw1 = 0xF000 | (S << 10) | imm10
    hw2 = 0xD000 | (j1 << 13) | (j2 << 11) | imm11
    return bytes([hw1 & 0xFF, hw1 >> 8, hw2 & 0xFF, hw2 >> 8]).hex()

def build_blob(src, defines=()):
    cmd = ["python3", os.path.join(SCRIPT_DIR, "build.py"),
           os.path.join(SCRIPT_DIR, src), "--json", *defines]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit(f"build.py failed for {src}:\n{r.stderr or r.stdout}")
    return json.loads(r.stdout)

def _fn(blob, name):
    for f in blob["functions"]:
        if f["name"] == name:
            return f
    raise SystemExit(f"{blob.get('src', '?')}: function {name!r} not found")

def find_mainapp(img):
    n = struct.unpack_from('<I', img, 8)[0]
    for i in range(n):
        _eid, off, _size, _crc = struct.unpack_from('<IIII', img, 0x40 + i * 16)
        name = bytes(img[off + 48:off + 128]).split(b'\0')[0].decode('latin1')
        if name.endswith('s200_firmware_ota.bin'):
            ps = struct.unpack_from('<I', img, off + 8)[0]
            return i, off, ps
    raise SystemExit("main-app component (ota/s200_firmware_ota.bin) not found")

def crc32c_msb(buf, _t=[]):
    if not _t:
        for b in range(256):
            c = b << 24
            for _ in range(8):
                c = ((c << 1) ^ 0x1edc6f41) & 0xffffffff if c & 0x80000000 else (c << 1) & 0xffffffff
            _t.append(c)
    crc = 0
    for byte in buf:
        crc = ((crc << 8) & 0xffffffff) ^ _t[((crc >> 24) ^ byte) & 0xff]
    return crc

def hx(s):
    return bytes.fromhex(s.replace(" ", ""))

def layout(img):
    """Compile runtime_main_22434.c and append at the tail of the main-app payload.
    Returns (append_bytes, in_place_patches, (idx, comp_off, old_ps)). No baked fn-ptrs
    are needed (every firmware call is via an absolute-const fn-ptr, and the RX hook is a
    bl target resolved from the blob's function table), so a single build pass suffices."""
    idx, comp_off, old_ps = find_mainapp(img)

    blob_off = align_up(old_ps, BLOB_ALIGN)
    base = mram_addr(blob_off)
    b = build_blob("runtime_main_22434.c")
    blob = bytes.fromhex(b["text"])
    rx_hook_addr = base + _fn(b, "rt_rx_hook")["offset"]   # bl target (even; Thumb bit not needed for bl)

    pad = blob_off - old_ps
    end_off = blob_off + len(blob)
    append = bytearray(end_off - old_ps)
    append[pad:pad + len(blob)] = blob

    prog_end = mram_addr(end_off)
    rodata = b.get("rodata_len", 0)
    print(f"  loader blob @ MRAM 0x{base:08x}  +{len(blob)} B "
          f"(.text {b['text_len'] - rodata} + rodata {rodata})")
    print(f"    rt_rx_hook @ MRAM 0x{rx_hook_addr:08x}")
    if prog_end > APP_MAX_END:
        over = prog_end - APP_MAX_END
        raise SystemExit(
            f"appended image is too large: programmed region ends at 0x{prog_end:08x}, "
            f"{over} B past the safe ceiling 0x{APP_MAX_END:08x}. The bootloader does NOT "
            "bounds-check this, so flashing would risk clobbering the OTA flag / NV or "
            "bricking the lens (SWD-only recovery). Reduce the injected code.")
    print(f"    appended {len(append)} B -> payload end MRAM 0x{prog_end:08x} "
          f"({(APP_MAX_END - prog_end) // 1024} KB under 0x{APP_MAX_END:08x})")

    site, stock = RX_HOOK_SITE
    in_place = [
        (g2f(site), stock, enc_bl(site, rx_hook_addr),
         f"bl rt_rx_hook @ {site:#x} (RUNTIME_SID dispatch, else tail-call stock dispatcher)"),
    ]
    return bytes(append), in_place, (idx, comp_off, old_ps)

def build_patch_ops(img):
    """Return (patched_data, ops). `ops` is a clang-free {offset, old, new, desc} list
    that reproduces patched_data from the stock image (same contract as patch_compress)."""
    append, in_place, (idx, comp_off, old_ps) = layout(img)

    data = bytearray(img)
    ops = []

    def record(off, newb, desc):
        newb = bytes(newb)
        old = bytes(img[off:off + len(newb)])
        if newb == old:
            return
        ops.append({"offset": off, "old": old.hex(), "new": newb.hex(), "desc": desc})
        data[off:off + len(newb)] = newb

    print("applying in-place edits:")
    for off, orig, new, desc in in_place:
        o, n = hx(orig), hx(new)
        cur = bytes(data[off:off + len(o)])
        assert cur == o, f"{off:#x} ({desc}): expected {o.hex()} got {cur.hex()} (run against the STOCK image)"
        record(off, n, desc)
        print(f"  {off:#x}: {desc} ({len(n)} B)")

    # append the loader blob to the main-app payload (last component -> shifts nothing)
    payload_end = comp_off + 128 + old_ps
    assert payload_end == len(data), (
        f"main-app payload ends at 0x{payload_end:x} but file is 0x{len(data):x}; the append "
        "model assumes ota/s200_firmware_ota.bin is the last component")
    ops.append({"offset": payload_end, "old": "", "new": bytes(append).hex(),
                "desc": "append loader blob to main-app payload"})
    data.extend(append)
    new_ps = old_ps + len(append)

    # fix the size/offset metadata the container + bootloader read
    record(comp_off + 8, struct.pack('<I', new_ps), "main-app subheader payload size (ps)")
    record(0x40 + idx * 16 + 8, struct.pack('<I', new_ps + 128), "main-app TOC entry size (ps + 128)")
    pre0 = struct.unpack_from('<I', data, comp_off + 128)[0]
    record(comp_off + 128,
           struct.pack('<I', (pre0 & 0xff000000) | (new_ps & 0xffffff)),
           "main-app preamble length (low 24 bits)")
    print(f"  appended {len(append)} B: ps {old_ps} -> {new_ps}, "
          f"preamble len -> 0x{new_ps & 0xffffff:x}, load addr 0x{APP_LOAD_ADDR:08x}")

    # recompute checksums (preamble crc32 first, then per-component crc32c)
    print("recomputing checksums:")
    n = struct.unpack_from('<I', data, 8)[0]
    for i in range(n):
        eid, off, size, _ = struct.unpack_from('<IIII', data, 0x40 + i * 16)
        ps = struct.unpack_from('<I', data, off + 8)[0]
        name = bytes(data[off + 48:off + 128]).split(b'\0')[0].decode('latin1')
        pre = None
        if name.endswith('s200_firmware_ota.bin'):
            pre = zlib.crc32(bytes(data[off + 128 + 8:off + 128 + ps])) & 0xffffffff
            record(off + 128 + 4, struct.pack('<I', pre), f"[{i}] {name} preamble crc32")
        crc = crc32c_msb(bytes(data[off + 128:off + 128 + ps]))
        record(0x40 + i * 16 + 12, struct.pack('<I', crc), f"[{i}] {name} component crc32c (TOC)")
        record(off + 12, struct.pack('<I', crc), f"[{i}] {name} component crc32c (subheader)")
        if pre is not None or crc32c_msb(bytes(img[off + 128:off + 128 + ps])) != crc:
            extra = f", preamble crc32={pre:08x}" if pre is not None else ""
            print(f"  [{i}] {name}: component crc32c={crc:08x}{extra}")

    return bytes(data), ops

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "g2_2.2.4.34.bin"
    dst = sys.argv[2] if len(sys.argv) > 2 else "g2_2.2.4.34_loader.bin"
    print("compiling loader blob (build.py):")
    img = open(src, "rb").read()
    data, ops = build_patch_ops(img)

    # Prove the clang-free op list reproduces the compiled image exactly.
    sys.path.insert(0, SCRIPT_DIR)
    from apply_patches import apply_ops
    assert apply_ops(img, ops) == data, "op list does not reproduce the compiled image"

    open(dst, "wb").write(data)
    # also emit the op list + manifest for the record / clang-free re-apply
    with open(os.path.join(SCRIPT_DIR, "loader_patches.json"), "w") as f:
        json.dump({"base": os.path.basename(src), "ops": ops}, f, indent=1)
    print(f"wrote {dst} ({len(data)} bytes)  and patches/loader_patches.json ({len(ops)} ops)")

if __name__ == "__main__":
    main()
