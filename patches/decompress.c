#include <stdint.h>

/*
 * G2 custom-firmware image decompressors.
 *
 * These are compiled to position-independent Thumb-2 and injected into reclaimed
 * firmware space, then called from the ImageRawDataUpdate handler when a
 * fragment carries a CompressMode flag. They must be SELF-CONTAINED: no malloc,
 * no external calls (no memcpy/memset/__aeabi_*), no global/static data. That
 * keeps the emitted .text relocation-free and freely relocatable.
 *
 * 4bpp output format (must match what the uncompressed path produces, see
 * g2-kit images.md): two pixels per byte, HIGH nibble = left pixel, on=0xF,
 * off=0x0.
 */

/*
 * 1bpp monochrome -> 4bpp expand.
 *
 * Source is 1 bit per pixel, MSB-first (bit7 of src[0] = leftmost pixel). Each
 * source byte (8 px) expands to 4 dest bytes. A set bit -> nibble 0xF (on), a
 * clear bit -> 0x0 (off).
 *
 *   src      compressed 1bpp bytes (message fragment payload)
 *   src_len  number of source bytes
 *   dst      output cursor inside the image reconstruction buffer
 *   dst_max  bytes remaining in that buffer; never write past it
 *
 * returns the number of bytes written to dst.
 */
uint32_t decompress_1to4(const uint8_t *src, uint32_t src_len,
                         uint8_t *dst, uint32_t dst_max) {
    uint32_t o = 0;
    for (uint32_t i = 0; i < src_len; i++) {
        uint32_t b = src[i];
        /* pixel pairs MSB-first: (7,6) (5,4) (3,2) (1,0) -> one dest byte each */
        for (int k = 7; k >= 1; k -= 2) {
            if (o >= dst_max) return o;
            uint8_t hi = ((b >> k)       & 1u) ? 0xF0 : 0x00;
            uint8_t lo = ((b >> (k - 1)) & 1u) ? 0x0F : 0x00;
            dst[o++] = (uint8_t)(hi | lo);
        }
    }
    return o;
}

/*
 * Injected fragment writer — this is the function actually patched into the
 * firmware. It replaces the per-fragment memcpy (FUN_00439be4) in the
 * ImageRawDataUpdate handler, so it MUST keep the memcpy ABI:
 *     r0 = dst, r1 = src, r2 = len   (returns dst; caller ignores it)
 *
 * `len` is the OUTPUT (4bpp) byte count the firmware already tracks. When the
 * current image update sets CompressMode != 0, the fragment payload is 1bpp and
 * we expand it (len/4 source bytes -> len output bytes), matching the 4bpp size
 * the sender declared. When CompressMode == 0 we copy verbatim, i.e. byte-for-
 * byte identical to the stock path.
 *
 * CompressMode is read straight from the decoded-message buffer the firmware
 * keeps at the fixed pointer in the literal at 0x0050066c. The ImgRawMsg fields
 * start at buffer+4 (a 4-byte cmd/subcmd header precedes them), and the handler
 * reads CompressMode at fieldbase+0x1c — i.e. buffer+0x20. (Verified against the
 * firmware's own "compress_mode = %d" log, which loads [r4,#0x1c] with
 * r4 = r5+4 = bufferbase+4. buffer+0x1c is total_size, which is why an earlier
 * +0x1c read expanded *every* fragment.) Reading a fixed absolute address
 * compiles to a literal load with no relocation, so this stays relocatable.
 *
 * Self-contained: no malloc, no external calls (the copy is an open-coded loop,
 * not memcpy), no writable globals.
 */
void *frag_write(uint8_t *dst, const uint8_t *src, uint32_t len) {
    const uint8_t *msg = *(const uint8_t *const *)0x0050066cU;
    uint32_t compress = *(const volatile uint32_t *)(msg + 0x20);

    if (compress == 0) {                    /* stock behaviour: plain copy */
        for (uint32_t i = 0; i < len; i++) dst[i] = src[i];
        return dst;
    }

    uint32_t nin = len >> 2;                /* 4 output bytes per source byte */
    uint32_t o = 0;
    for (uint32_t i = 0; i < nin; i++) {
        uint32_t b = src[i];
        for (int k = 7; k >= 1; k -= 2) {
            uint8_t hi = ((b >> k)       & 1u) ? 0xF0 : 0x00;
            uint8_t lo = ((b >> (k - 1)) & 1u) ? 0x0F : 0x00;
            dst[o++] = (uint8_t)(hi | lo);
        }
    }
    return dst;
}
