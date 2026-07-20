"""
Verify the CORRECTED wire frames decode to the right payload offsets, by running the
real firmware decoder (RxFrameDataProcess) and dumping the union at offset 4.

Frame format (confirmed): outer{ field1(tag1,varint)=DISC, field(DISC+2)(submsg)=payload }
  -> decoded struct: disc@0, seq@1, which_msg@2, union@4
"""
from g2emu import G2Emu

RX_FRAME_PROC = 0x005cf8a8

def varint(n):
    out = []; v = n & 0xFFFFFFFF
    while True:
        b = v & 0x7f; v >>= 7
        if v: b |= 0x80
        out.append(b)
        if not v: break
    return bytes(out)

def tag(f, w): return varint((f << 3) | w)
def vfield(f, v): return tag(f, 0) + varint(v)
def bfield(f, data): return tag(f, 2) + varint(len(data)) + data

def frame(disc, payload_fields, magic=7):
    """field1=disc(msgType) ; field2=magic(seq/dedup) ; oneof field(disc+2)=submessage(payload)"""
    sub = b"".join(payload_fields)
    return vfield(1, disc) + vfield(2, magic) + bfield(disc + 2, sub)

def decode(label, raw, dump=16):
    e = G2Emu()
    p = e.malloc_scratch(len(raw)+16); e.wr(p, raw)
    out = e.malloc_scratch(0x900); e.wr(out, b"\xEE"*0x900)
    rc = e.call(RX_FRAME_PROC, [p, len(raw), out])
    print("\n%s" % label)
    print("  bytes: %s" % raw.hex())
    print("  rc=%d  disc@0=%d which@2=%d" % (rc & 0xffffffff, e.u8(out), int.from_bytes(e.rd(out+2,2),'little')))
    print("  union@4: %s" % e.rd(out+4, dump).hex())
    return e, out

if __name__ == "__main__":
    # session_status D=4: {status@0:u8=1, id@4:u32=1}
    e, out = decode("session_status D=4 {status=1,id=1}",
                    frame(4, [vfield(1, 1), vfield(2, 1)]))
    print("  -> status(union+0)=%d  id(union+4)=%d" % (e.u8(out+4), e.u32(out+8)))

    # host_status D=2: {status@0:u8=2}
    e, out = decode("host_status D=2 {status=2}", frame(2, [vfield(1, 2)]))
    print("  -> status(union+0)=%d" % e.u8(out+4))

    # session_id_changed D=10: {id@0:u32=1}
    e, out = decode("session_id_changed D=10 {id=1}", frame(10, [vfield(1, 1)]))
    print("  -> id(union+0)=%d" % e.u32(out+4))

    # agent_content D=5: style@0,text@4,op@0x204,id@0x208,event@0x20c,session_id@0x210
    e, out = decode("agent_content D=5 {style=1,text=HELLO,op=1,id=1,event=4,session_id=1}",
                    frame(5, [vfield(1, 1), bfield(2, b"HELLO"), vfield(3, 1),
                              vfield(4, 1), vfield(5, 4), vfield(6, 1)]), dump=32)
    print("  -> style(u+0)=%d text_len(u+2)=%d text(u+4)=%r op(u+0x204)=%d id(u+0x208)=%d event(u+0x20c)=%d sid(u+0x210)=%d"
          % (e.u8(out+4), int.from_bytes(e.rd(out+6,2),'little'),
             e.rd(out+8, 5), e.u8(out+4+0x204), e.u32(out+4+0x208),
             e.u8(out+4+0x20c), e.u32(out+4+0x210)))
