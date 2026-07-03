#!/usr/bin/env python3
"""
Build a CFW image for g2_2.2.4.34 with:
  (1) the 576x288 image-container size lift (same 3 edits as
      patches/patch_img_container_576.py),
  (2) 1bpp->4bpp image decompression on ImageRawDataUpdate.CompressMode, and
  (3) a CFW capability-advertisement field (protobuf field 100, a feature-token
      string) appended to the sid=0x09 settings READ response, so a connected
      app can detect this firmware and which extensions it supports.

(2) injects frag_write() (patches/decompress.c, built by build.py) over the
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

# zlib image glue (patches/zlib_glue.c -> build.py pass2, 1394 B) placed at
# ghidra 0x491400 (= bufbase set_aging_test_info tail, after frag_write). Exports
# zwrap_alloc@0x491400, zwrap_free@0x49140e, load_image_z@0x49141a. Mode dispatch:
# 'B'=raw BMP, 1=zlib 4bpp BMP, 6=zlib headerless-4bpp -> all decoded by our own fast
# nibble->8bpp expander (NOT the stock per-pixel-palette loader); 2=zlib 8bpp full frame
# ->display buffer, 3=8bpp XOR delta, 4=8bpp stereo pair (per-lens via FW_SIDE); 5=play a
# buzzer UI sound (0 preset/1 note/2 stop/3 raw tone; no display change). 2/3/4/6 + the
# BMP decoder push via the loader tail; stock FW_LOADBMP kept only as a fallback.
ZLIB_GLUE = bytes.fromhex(
    "02fb01f042f66f31c0f247010847084642f6b331c0f2470108472de9f04fd5b0804645f6c340c0f2500015460f46804747b13db197f80090b9f1050f09d0b9f1420f18d1404639462a4655b0bde8f04fcfe1022dc0f0c881787843d0002841d1b878082800f2c08149f25971c0f24e0196318847b8e1032de4d3a9f1070010f1070fdfd9b8f84040b8f84260002047a9002200bf88540132382afbd1791c681ecde9471041f20141c0f249014f910e3106fb04f250910021b9f1010f5191069202d0b9f1060f55d1611cb9f1010f4fea5101039120d1033121f00301714301f1b6051be0052d5cd301285ad1b8780025411e062900f27981f978032900f275813a79002a00f0718149f25973c0f24e0303f59a73984767e101fb06f515eb000a4ff0000040f1000bbaeb02007bf1000002d2501b074407e042f66f31c0f2470128468847074648b3cde904464ef20764c0f25b0448f2e45204f13c0647a8c0f278020f213823cde94a75b04708b347a8a0479ce04ef2076ac0f25b0a48f2e452d8f808500af13c0747a8c0f278020f213823b847002859d047a8d0474ff0ff3523e102281bd149f25970c0f24e0080471ae104f5857247a8042190474c99064647a80291a047012e71d1b9f1010f55d1029a4046394600f00cf9054669e0072d4ff00005c0f00181032840f0fe80b878fa78397940ea02207d79be7901284ff0010498bf204644f62062904228bf104649f25972c0f24e0202f5e272642928bf6421904744f24040c2f207000068002800f0da8045ea062148f2eb42012988bf0c46c0f2440221469047cde0b9f1030f03953ed0b9f1020f6ed14a95069d0af5857247a804214b959047012894d14c980596401bb0fa80f04609aae00298a84215d1d8f80800002502900195ddf81090059e039c39464a463346009400f00ff9029940464a46334600f032f901e04ff0ff350698baeb00007bf10000c0f0958042f66f30c0f2470000f14401384688478be0cde90446069900240df11c0b0af5857a0df58e79081bb0f5807f28bf4ff48070cde94ab048460021d0474a99b1eb0b050cd003995b460a19294613f8016b1778013987ea060702f8017bf6d101282c444cd0069900284ff000064cd1b5fa85f04009d7d047e04af6ed00c0f24500cde904468047871e069818bf074629463d185046cc1b00260df11c0a00f585704ff0000906904ff48070069a4b9047a80021cdf828a19047ddf828e1beeb0a0c10d04b4652466146bb4205d3ab423cbf92f800b004f803b0013902f1010203f10103f1d1e144beeb0a0118bf0121a94528bf012608d238b90029d4d104e00698201ab0fa80f04609049c4ef2076ac0f25b0a47a8d0470399002e3ff4dfae059b4046224600f094f80025284655b0bde8f08ff0b583b00029044657d0362a55d30878422852d148784d284fd1087f4b7f40ea0320042849d1887dcb7d0f7e40ea032040ea07404b7e8f7cce7c50ea036047ea06230f7d4e7d43ea074343ea0665064648bf4642b4f8403000284ff00000c8bf01209d4229d1b4f842309e4225d18b7acf7a91f80cc043ea07234f7b43ea0c4343ea0763934218d26a1c032707eb5202a76822f0030c1944019038462a463346cdf800c000f012f8204639462a46334600f035f8002003b0f0bd41f24b63c0f25003204603b0bde8f040184733b32de9f043dde907ec4ff00008bcf1000f45466fea080618bf9d198ab105fb0e19002600bf770819f80770f50707f00f0408bf3c0944ea041484550136b242f1d108f1010898451044e0d1bde8f04370472de9f04182b003fb02f68846cde9001642f6877107466846c0f247011c461546884740f2196047f8240f788940f6017245ea0040b86045ea044057f8204c7860c0f24b0220463946fe60c7f81080904740f2f751c0f244012046884702b0bde8f081"
)

# settings capability-advertisement wrapper (patches/settings_ext.c ->
# build.py, 256 B) placed at ghidra 0x491972 (dead set_aging_test_info tail,
# after the zlib glue). Hooks the one `bl FUN_0047398c` (aa21 send) at the tail
# of the settings responder FUN_004b42b4: appends protobuf field 100 (string
# "EVENCFW/1 img576 imgz xordelta stereo") to the sid=0x09 READ response so a
# connected app can detect this CFW and its extensions, then tail-calls send.
SETTINGS_EXT = bytes.fromhex(
    "092978d12de9f04102eb030c56248cf804404e248cf8064043248cf8074046248c"
    "f8084057248cf809402f248cf80a4031244ff0a20e8cf80b406924352702f803e0"
    "4ff0060e8cf80d408cf8107037278cf814407a248cf801e04ff0250e67268cf811"
    "7036278cf8174078248cf802e04ff0450e6d258cf80f608cf812708cf816608cf8"
    "194064266c2761248cf803e08cf805e04ff0200e8cf80e508cf815504ff06f0872"
    "258cf81c6065268cf81e7074278cf82040732428338cf80ce08cf813e08cf818e0"
    "8cf81a808cf81b508cf81d608cf81f708cf821e08cf822408cf823708cf824608c"
    "f825508cf826608cf82780bde8f04143f68d1cc0f2470c6047"
)

# frag_write machine code (patches/decompress.c -> build.py, text+0x80, 106 B)
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
    # --- CFW capability advertisement on the sid=0x09 settings READ response ---
    # Inject settings_send_wrapper into the dead tail (after the zlib glue), then
    # redirect the settings responder's `bl FUN_0047398c` (aa21 send) to it so it
    # appends protobuf field 100 ("EVENCFW/1 img576 imgz xordelta stereo") before
    # framing. Unknown high field tag -> stock app/bridge ignore it; CFW-aware
    # apps read it to detect the firmware and gate features.
    (g2f(0x491972), "36 e0 4f f4", SETTINGS_EXT.hex(), "settings_send_wrapper (CFW caps field)"),
    (g2f(0x4b43c4), "bf f7 e2 fa", "dd f7 d5 fa", "bl settings_send_wrapper (append caps field 100)"),
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
    src = sys.argv[1] if len(sys.argv) > 1 else "g2_2.2.4.34.bin"
    dst = sys.argv[2] if len(sys.argv) > 2 else "g2_2.2.4.34_cfw.bin"
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
