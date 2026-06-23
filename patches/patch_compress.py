#!/usr/bin/env python3
"""
Build a CFW image for g2_2.2.4.34 with:
  (1) the 576x288 image-container size lift (same 3 edits as
      g2flash/patch_img_container_576.py), and
  (2) 1bpp->4bpp image decompression on ImageRawDataUpdate.CompressMode.

(2) injects frag_write() (g2flash/patches/decompress.c, built by build.py) over the
unused production-test handler set_aging_test_info (ghidra 0x491340, ~2KB, zero
xrefs) and retargets the three per-fragment memcpy calls (FUN_00439be4) in the
ImageRawDataUpdate handler FUN_004ff8fc to it.

frag_write keeps the memcpy ABI (r0=dst,r1=src,r2=len) and reads CompressMode
itself from the decoded-message buffer (*(0x0050066c)+0x1c). When CompressMode!=0
it treats len as the OUTPUT (4bpp) size and expands len/4 1bpp source bytes; the
sender therefore declares MapTotalSize / MapFragmentPacketSize in 4bpp units and
puts 1bpp bytes in MapRawData. CompressMode==0 is a byte-identical plain copy, so
stock (uncompressed) image updates are unaffected.

Length-preserving; recomputes the EVENOTA component CRC32C (TOC + sub-header echo)
and the mainApp preamble zlib-CRC32, exactly like patch_img_container_576.py.
"""
import sys, struct, zlib

DELTA = 0x39E680  # file_off = ghidra_addr - DELTA  (OTA mainApp component)

def g2f(addr):
    return addr - DELTA

# zlib image glue (g2flash/patches/zlib_glue.c -> build.py pass2, 386 B) placed at
# ghidra 0x491400 (= bufbase set_aging_test_info tail, after frag_write). Exports
# zwrap_alloc@0x491400, zwrap_free@0x49140e, load_image_z@0x49141a. load_image_z
# decompresses into the recon buffer's unused tail (no scratch malloc) to avoid OOM.
ZLIB_GLUE = bytes.fromhex(
    "02fb01f042f66f31c0f247010847084642f6b331c0f2470108472de9f04f8fb0"
    "41f24b6314460d4606460029c0f2500300f09e80022cc0f09b80287800f00f00"
    "082840f09580b6f840000323421cb6f8421003eb520222f003024a4302f1b607"
    "01fb00fb17eb040a4ff0000040f10009bbeb0a0170eb090012d242f66f31c0f2"
    "470138468847804670b941f24b63304629462246c0f250030fb0bde8f04f1847"
    "abeb070005eb0008002001a9002200bf88540132382afbd141f20140c0f24900"
    "4ef2076109900e30c0f25b010a90002048f2e452cde904870b9001f13c0701a8"
    "c0f278020f213823cde90154b84760bb4ef20760c0f25b0000f5857201a80421"
    "90470699074600914ef2076101a8c0f25b018847012f18d1009a41f24b633046"
    "4146c0f250039847bbeb0a014ff0000171eb0901044620d242f66f30c0f24700"
    "00f144014046884717e0bbeb0a004ff0000070eb090007d242f66f30c0f24700"
    "00f144014046884741f24b63c0f250033046294622469847044620460fb0bde8f08f"
)

# frag_write machine code (g2flash/patches/decompress.c -> build.py, text+0x80, 106 B)
FRAG_WRITE = bytes.fromhex(
    "f0b540f26c63c0f250031b681b6a13b35fea920c08bff0bd00238646ca5c0725"
    "744600bf22fa05f606f001066f1e764222fa07f726f00f06ff0718bf0f3604f8"
    "016b012da5f10205ecd1013363450ef1040ee3d108e03ab1034600bf11f8015b"
    "013a03f8015bf9d1f0bd"
)

# (file_offset, expected_original, new_bytes, description)
PATCHES = [
    # --- 576x288 image-container size lift ---
    (g2f(0x501062), "bd f8 2c 10", "40 f2 41 20", "container width  <= 576"),
    (g2f(0x50112a), "bd f8 2e 00", "40 f2 21 11", "container height movw #0x121"),
    (g2f(0x50112e), "91 28",       "88 42",       "container height cmp r0,r1"),
    # --- inject frag_write over set_aging_test_info (production-test, unused) ---
    (g2f(0x491340), "ab f7 97 fe", FRAG_WRITE.hex(), "frag_write() decompress shim"),
    # --- retarget the 3 per-fragment memcpy calls -> frag_write ---
    (g2f(0x500984), "39 f7 2e f9", "90 f7 dc fc", "bl frag_write (first fragment)"),
    (g2f(0x500b60), "39 f7 40 f8", "90 f7 ee fb", "bl frag_write (new-stream restart)"),
    (g2f(0x500d7c), "38 f7 32 ff", "90 f7 e0 fa", "bl frag_write (append fragment)"),
    # --- allow per-fragment CompressMode to vary within one image session ---
    # The append path stashes fragment 0's CompressMode and rejects any later
    # fragment whose CompressMode differs (cmp at 0x500c0e). Make that branch
    # unconditional (beq->b) so a sender can mix a verbatim CompressMode=0 BMP
    # header fragment with CompressMode=1 1bpp pixel fragments in one stream.
    (g2f(0x500c10), "3b d0", "3b e0", "drop per-session CompressMode-consistency guard"),
    # --- zlib (DEFLATE) whole-image decompression at BMP-load time ---
    # Inject the glue blob into the dead set_aging_test_info tail, then redirect
    # the one BMP-loader call FUN_0050164a(state, reconBuf, len) in FUN_004ae69c
    # to load_image_z, which inflates a zlib stream (sent as a CompressMode=0
    # image) into a scratch BMP before loading. Raw BMPs pass straight through.
    (g2f(0x491400), "ab f7 21 fd", ZLIB_GLUE.hex(), "zlib glue (zwrap_alloc/free + load_image_z)"),
    (g2f(0x4ae9cc), "52 f0 3d fe", "e2 f7 25 fd", "bl load_image_z (decompress at BMP load)"),
]

def hx(s):
    return bytes.fromhex(s.replace(" ", ""))

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

def fixup_checksums(data):
    n = struct.unpack_from('<I', data, 8)[0]
    for i in range(n):
        eid, off, size, _ = struct.unpack_from('<IIII', data, 0x40 + i * 16)
        ps = struct.unpack_from('<I', data, off + 8)[0]
        name = bytes(data[off + 48:off + 128]).split(b'\0')[0].decode('latin1')
        if name.endswith('s200_firmware_ota.bin'):
            pre = zlib.crc32(bytes(data[off + 128 + 8:off + 128 + ps])) & 0xffffffff
            struct.pack_into('<I', data, off + 128 + 4, pre)
        crc = crc32c_msb(bytes(data[off + 128:off + 128 + ps]))
        struct.pack_into('<I', data, 0x40 + i * 16 + 12, crc)
        struct.pack_into('<I', data, off + 12, crc)
        extra = f", preamble crc32={pre:08x}" if name.endswith('s200_firmware_ota.bin') else ""
        print(f"  [{i}] {name}: component crc32c={crc:08x}{extra}")

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "g2flash/g2_2.2.4.34.bin"
    dst = sys.argv[2] if len(sys.argv) > 2 else "g2flash/g2_2.2.4.34_cfw.bin"
    data = bytearray(open(src, "rb").read())
    for off, orig, new, desc in PATCHES:
        o, n = hx(orig), hx(new)  # orig is a prefix sanity-check; new may be longer (code blob)
        if bytes(data[off:off + len(n)]) == n:
            print(f"  {off:#x}: already patched ({desc})")
            continue
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
