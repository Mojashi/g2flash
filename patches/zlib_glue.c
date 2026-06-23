#include <stdint.h>

/*
 * zlib (DEFLATE) image support for the G2 CFW.
 *
 * The stock image path loads a 4bpp BMP from the reassembled buffer via the BMP
 * decoder FUN_0050164a(state, bmp, len). We wrap that call: if the reassembled
 * buffer is a zlib stream (low nibble of byte0 == 8 == CM_DEFLATE), we inflate
 * it into a scratch BMP and load that; otherwise we pass through unchanged.
 *
 * So the sender just zlib-compresses a whole normal BMP and streams it as an
 * ordinary CompressMode=0 image (frag_write copies it verbatim into the recon
 * buffer); decompression happens here, at load time. This is independent of the
 * 1bpp frag_write path and gives real DEFLATE on arbitrary 4bpp images.
 *
 * The firmware's zlib uses a pool allocator that needs a heap handle we don't
 * have a clean global for, so instead we drive the inflate primitives directly
 * with our own zalloc/zfree that wrap the image system's heap-free global malloc
 * (FUN_00472b6e / FUN_00472bb2). Everything is called by absolute address
 * (constant -> movw/movt, no relocation), so the blob stays freely placeable.
 *
 * Self-contained: no external symbols, no writable globals. The only
 * placement-dependent constants are ZWRAP_ALLOC_ADDR / ZWRAP_FREE_ADDR (the
 * runtime addresses of zwrap_alloc/zwrap_free once injected) — filled in on the
 * second build pass once their offsets and the placement base are known.
 */

typedef void *(*malloc_fn)(uint32_t);
typedef void (*free_fn)(void *);
typedef int (*inflateInit2_fn)(void *strm, int windowBits, const char *ver, int ssize);
typedef int (*inflate_fn)(void *strm, int flush);
typedef int (*inflateEnd_fn)(void *strm);
typedef int (*loadbmp_fn)(void *state, void *bmp, uint32_t len);

/* firmware entry points (Thumb bit set for blx via constant pointer) */
#define FW_MALLOC  ((malloc_fn)0x00472b6fU)        /* FUN_00472b6e malloc(size) */
#define FW_FREE    ((free_fn)0x00472bb3U)          /* FUN_00472bb2 free(ptr) */
#define FW_INIT2   ((inflateInit2_fn)0x005be643U)  /* FUN_005be642 inflateInit2_ */
#define FW_INFLATE ((inflate_fn)0x005be711U)       /* FUN_005be710 inflate */
#define FW_END     ((inflateEnd_fn)0x005be607U)    /* FUN_005be606 inflateEnd */
#define FW_LOADBMP ((loadbmp_fn)0x0050164bU)       /* FUN_0050164a BMP decoder */
#define ZLIB_VER   ((const char *)0x007885e4U)     /* "1.1.4" */

#ifndef ZWRAP_ALLOC_ADDR
#define ZWRAP_ALLOC_ADDR 0u   /* pass-2 placeholder */
#define ZWRAP_FREE_ADDR  0u
#endif

/* z_stream (zlib 1.1.4, sizeof = 0x38) field offsets */
#define ZS_NEXT_IN   0x00
#define ZS_AVAIL_IN  0x04
#define ZS_NEXT_OUT  0x0c
#define ZS_AVAIL_OUT 0x10
#define ZS_TOTAL_OUT 0x14
#define ZS_ZALLOC    0x20
#define ZS_ZFREE     0x24
#define ZS_OPAQUE    0x28
#define ZS_SIZE      0x38

void *zwrap_alloc(void *opaque, uint32_t items, uint32_t size) {
    (void)opaque;
    return FW_MALLOC(items * size);
}

void zwrap_free(void *opaque, void *ptr) {
    (void)opaque;
    FW_FREE(ptr);
}

int load_image_z(void *state, uint8_t *src, uint32_t srclen) {
    /* zlib stream? CMF low nibble == 8 (deflate). A BMP starts with 'B' (0x42). */
    if (src != 0 && srclen >= 2 && (src[0] & 0x0f) == 8) {
        uint32_t w = *(uint16_t *)((uint8_t *)state + 0x40);
        uint32_t h = *(uint16_t *)((uint8_t *)state + 0x42);
        /* exact 4bpp BMP file-size upper bound (14+40 hdrs + 64 palette + padded rows) */
        uint32_t row_stride = (((w + 1) >> 1) + 3) & ~3u;
        uint32_t bmp_max = 118 + row_stride * h + 64;

        /* The recon buffer `src` was allocated w*h bytes at container creation but
         * only holds the small compressed stream, so decompress into its unused
         * tail and skip the scratch malloc entirely (it fails under heap pressure
         * with many tiles). Only fall back to a malloc when the compressed input
         * would overlap the output region. */
        uint32_t recon_size = w * h;
        uint8_t *dst;
        int allocated = 0;
        if ((uint64_t)bmp_max + srclen <= recon_size) {
            dst = src + (recon_size - bmp_max);
        } else {
            dst = (uint8_t *)FW_MALLOC(bmp_max);
            if (dst == 0) return FW_LOADBMP(state, src, srclen);
            allocated = 1;
        }

        uint8_t strm[ZS_SIZE];
        for (uint32_t i = 0; i < ZS_SIZE; i++) strm[i] = 0;
        *(uint8_t **)(strm + ZS_NEXT_IN) = src;
        *(uint32_t *)(strm + ZS_AVAIL_IN) = srclen;
        *(uint8_t **)(strm + ZS_NEXT_OUT) = dst;
        *(uint32_t *)(strm + ZS_AVAIL_OUT) = bmp_max;
        *(uint32_t *)(strm + ZS_ZALLOC) = ZWRAP_ALLOC_ADDR;
        *(uint32_t *)(strm + ZS_ZFREE) = ZWRAP_FREE_ADDR;
        *(uint32_t *)(strm + ZS_OPAQUE) = 0;
        if (FW_INIT2(strm, 15, ZLIB_VER, ZS_SIZE) == 0) {
            int r = FW_INFLATE(strm, 4);                 /* Z_FINISH */
            uint32_t out = *(uint32_t *)(strm + ZS_TOTAL_OUT);
            FW_END(strm);
            if (r == 1) {                                /* Z_STREAM_END */
                int ret = FW_LOADBMP(state, dst, out);
                if (allocated) FW_FREE(dst);
                return ret;
            }
        }
        if (allocated) FW_FREE(dst);
        /* fall through on any failure: load raw (decoder will reject cleanly) */
    }
    return FW_LOADBMP(state, src, srclen);
}
