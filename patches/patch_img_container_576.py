#!/usr/bin/env python3
"""
Binary patch: lift EvenHub image-container size limit from 288x144 to 576x288.
Applies to G2 firmware version 2.2.4.34 (will NOT cleanly apply to any other
version because offsets will change).

Target: common_image_container creation fn (Ghidra FUN_00500f7a) inside the
ota/s200_firmware_ota.bin component of the flash image. The fn rejects width
> 0x120 (288) and height > 0x90 (144). We widen both upper bounds to the full
screen (576x288) by reusing the firmware's own movw+cmp(reg,reg) pattern.

The width/height value is already live in r1/r0 at each upper-bound check (the
firmware redundantly reloads it), so we overwrite the redundant ldrh with a
movw of the new limit, leaving cmp/blt and the branch targets intact.

  width  @ ghidra 0x501062 / file 0x1629e2:
     ldrh.w r1,[sp,#0x2c]  (bd f8 2c 10)  ->  movw r0,#0x241  (40 f2 41 20)
     (existing) cmp r1,r0 / blt  ->  passes when width  < 0x241  (<=576)
  height @ ghidra 0x50112a / file 0x162aaa:
     ldrh.w r0,[sp,#0x2e]  (bd f8 2e 00)  ->  movw r1,#0x121  (40 f2 21 11)
     cmp r0,#0x91          (91 28)        ->  cmp r0,r1       (88 42)
     (existing) blt  ->  passes when height < 0x121  (<=288)

Min-size checks (>=0x14), position clamps, and alloc-failure handling are
untouched. The patch is length-preserving.

CHECKSUMS (this is why a code patch needs more than a byte poke): the EVENOTA
container stores, for each component, a CRC-32C of its payload in BOTH the TOC
(0x40+i*16 +12) and the component sub-header echo (componentOffset +0x0C). The
glasses recompute that CRC over the bytes they receive and reject the component
on END (status 7 = CHECK_FAIL) if it doesn't match the stored value — the
flasher just streams the sub-header verbatim, it does NOT recompute anything.
The mainApp payload additionally carries an internal zlib CRC-32 over payload
[0x08:] stored at payload +0x04, checked when the image is loaded. After
patching the mainApp bytes we must rewrite all of these, or the flash fails
(stale component CRC-32C) and/or the image won't boot (stale preamble CRC-32).
"""
import sys, struct, zlib

PATCHES = [
    # file_offset, original_bytes, new_bytes
    (0x1629e2, "bd f8 2c 10", "40 f2 41 20"),  # width  upper bound -> 576
    (0x162aaa, "bd f8 2e 00", "40 f2 21 11"),  # height movw #0x121
    (0x162aae, "91 28",       "88 42"),        # height cmp r0,r1
]

def hx(s): return bytes.fromhex(s.replace(" ", ""))

def crc32c_msb(buf, _t=[]):
    """CRC-32C, MSB-first, init=0, xorout=0 (NON-reflected) — the EVENOTA flavor."""
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

def fixup_checksums(data):
    """Recompute every component's stored CRC-32C (TOC + sub-header echo), and the
    mainApp internal preamble CRC-32, after the payload bytes have changed."""
    n = struct.unpack_from('<I', data, 8)[0]
    for i in range(n):
        eid, off, size, _ = struct.unpack_from('<IIII', data, 0x40 + i * 16)
        ps = struct.unpack_from('<I', data, off + 8)[0]
        name = bytes(data[off + 48:off + 128]).split(b'\0')[0].decode('latin1')
        # The mainApp internal preamble CRC-32 lives at payload+0x04 over payload[0x08:].
        # It is INSIDE the payload, so write it before computing the component CRC-32C.
        if name.endswith('s200_firmware_ota.bin'):
            pre = zlib.crc32(bytes(data[off + 128 + 8:off + 128 + ps])) & 0xffffffff
            struct.pack_into('<I', data, off + 128 + 4, pre)
        payload = bytes(data[off + 128:off + 128 + ps])
        crc = crc32c_msb(payload)
        struct.pack_into('<I', data, 0x40 + i * 16 + 12, crc)   # TOC entry
        struct.pack_into('<I', data, off + 12, crc)             # sub-header echo
        extra = f", preamble crc32={pre:08x}" if name.endswith('s200_firmware_ota.bin') else ""
        print(f"  [{i}] {name}: component crc32c={crc:08x}{extra}")

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "g2_2.2.4.34.bin"
    dst = sys.argv[2] if len(sys.argv) > 2 else "g2_2.2.4.34_imgcontainer576.bin"
    data = bytearray(open(src, "rb").read())
    for off, orig, new in PATCHES:
        o, n = hx(orig), hx(new)
        assert len(o) == len(n), (off, "length mismatch")
        cur = bytes(data[off:off + len(o)])
        if cur == n:
            print(f"  {off:#x}: already patched")
            continue
        assert cur == o, f"{off:#x}: expected {o.hex()} got {cur.hex()}"
        data[off:off + len(n)] = n
        print(f"  {off:#x}: {o.hex()} -> {n.hex()}")
    print("recomputing checksums:")
    fixup_checksums(data)
    open(dst, "wb").write(data)
    print(f"wrote {dst} ({len(data)} bytes)")

if __name__ == "__main__":
    main()
