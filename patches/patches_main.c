/*
 * Single translation unit for all injected CFW patch code.
 *
 * Historically the four patch sources below were each compiled and PLACED as a
 * separate relocatable blob, which meant they could not call one another and
 * patch_compress.py had to lay out four blobs at four base addresses (and special-
 * case extracting a single function out of decompress.c). Compiling them as ONE
 * translation unit instead yields a SINGLE blob: build.py's mini-linker resolves any
 * cross-file call/relocation, and every injected entry point is simply
 * base + its offset in the one blob.
 *
 * The four sources deliberately share no typedef / macro / function names, so a plain
 * #include chain compiles cleanly. Each keeps its own `#include <stdint.h>` (idempotent
 * via the standard header guard). Order is not significant — build.py looks functions
 * up by name — but decompress.c is first so the memcpy-ABI frag_write leads the blob.
 *
 * zlib_glue.c still expects ZWRAP_ALLOC_ADDR / ZWRAP_FREE_ADDR / SEQ_TICK_ADDR to be
 * -D-defined on the 2nd build pass (absolute Thumb fn-ptrs baked into the z_stream and
 * the buzzer osTimer); patch_compress.py passes them when it compiles THIS file.
 */
#include "decompress.c"
#include "zlib_glue.c"
#include "settings_ext.c"
#include "gesture_fwd.c"
#include "dbg_terminal.c"
#include "screenshot.c"
