// CFW capability advertisement.
//
// Appends one extra protobuf field to the sid=0x09 device-settings READ response
// (G2SettingPackage) right before it is framed and sent, so a connected app can
// detect this custom firmware and discover which extensions it supports without
// any timeout-based probing. The field is:
//
//   field 100, wire type 2 (length-delimited string):
//     "EVENCFW/<ver> <space-separated feature tokens>"
//
// Tag 100 is far above the stock message's fields (1..19), so stock decoders and
// the phone bridge skip it as an unknown field -- fully backward compatible.
//
// HOOK: the settings responder FUN_004b42b4 ends with
//     r0=type(1) r1=sid(9) r2=buf r3=len ; bl FUN_0047398c   ; aa21 send
// We retarget that one `bl` to settings_send_wrapper. The 4 send args are already
// in r0..r3, so the wrapper appends to `buf` (a 256-byte static response buffer
// at 0x200706cc that only uses ~40 B) and tail-calls the real sender with the
// grown length. Only this call site is redirected, but we still guard on sid==9.

typedef int (*send_fn)(int type, int sid, unsigned char *buf, unsigned len);

#define FW_SEND 0x0047398d /* FUN_0047398c | thumb bit */

// "EVENCFW/1 img576 imgz xordelta stereo"
//   EVENCFW/1  -> magic prefix + contract version (detect: starts-with "EVENCFW/")
//   img576     -> 576x288 image containers (vs stock 288x144 cap)
//   imgz       -> zlib (DEFLATE) compressed image payloads
//   xordelta   -> 8bpp XOR-delta frame updates (modes 2/3)
//   stereo     -> per-lens stereo image pairs (mode 4)
int settings_send_wrapper(int type, int sid, unsigned char *buf, unsigned len) {
    if (sid == 9) {
        unsigned char *p = buf + len;
        unsigned n = 0;
        p[n++] = 0xA2; p[n++] = 0x06;            // tag: (100<<3)|2 = 802
        p[n++] = 37;                             // payload length
        p[n++]='E';p[n++]='V';p[n++]='E';p[n++]='N';p[n++]='C';p[n++]='F';p[n++]='W';p[n++]='/';p[n++]='1';
        p[n++]=' ';
        p[n++]='i';p[n++]='m';p[n++]='g';p[n++]='5';p[n++]='7';p[n++]='6';
        p[n++]=' ';
        p[n++]='i';p[n++]='m';p[n++]='g';p[n++]='z';
        p[n++]=' ';
        p[n++]='x';p[n++]='o';p[n++]='r';p[n++]='d';p[n++]='e';p[n++]='l';p[n++]='t';p[n++]='a';
        p[n++]=' ';
        p[n++]='s';p[n++]='t';p[n++]='e';p[n++]='r';p[n++]='e';p[n++]='o';
        len += n;
    }
    return ((send_fn)FW_SEND)(type, sid, buf, len);
}
