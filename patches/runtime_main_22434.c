/*
 * runtime_main_22434.c — single translation unit for the 2.2.4.34 mode-runtime loader.
 * build.py compiles this one file into ONE position-independent blob (its mini-linker
 * resolves the intra-.text calls between runtime.c and the glue). patch_loader.py appends
 * the blob and redirects the RX-site bl at 0x0045aaa4 to rt_rx_hook.
 */
#include "runtime.c"
#include "runtime_hooks_22434.c"
