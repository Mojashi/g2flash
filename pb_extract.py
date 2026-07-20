#!/usr/bin/env python3
"""
Comprehensive nanopb descriptor extractor for g2_2.2.4.34.bin.

Reuses the VALIDATED field-descriptor decoder (decode_fields, from txagent_walk2.py —
cross-checked against real device traffic) and generalizes it from the single terminal
envelope root to EVERY pb_msgdesc_t in the image, by:
  1. Structurally scanning app rodata for pb_msgdesc_t-shaped structs
     {fields_ptr, submsg_info, 0, 0, field_count, field_count} (0x18 bytes).
  2. Parsing each descriptor's fields with decode_fields().
  3. Resolving submessage fields (ltype 8/9) to child descriptors via the submsg_info
     (ptrB) array, indexed by a running submessage counter.
Outputs a machine-readable JSON + a .proto-ish text dump, and validates that the known
terminal envelope (0x00777840, 25 fields) is reproduced.
"""
import struct, json

FW = "/Users/mojashi/repos/odd/g2flash/g2_2.2.4.34.bin"
BASE = 0x39E680
data = open(FW, "rb").read()
IMG_LO = 0x00438000
IMG_HI = 0x0078F188            # stock app code+rodata end (before any appended CFW blob)

def ok_addr(a): return IMG_LO <= a < IMG_HI and (a - BASE) < len(data)
def rd32(addr): return struct.unpack_from("<I", data, addr - BASE)[0]
def u16(x): return x & 0xFFFF
def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x

# ---- validated field-descriptor decoder (verbatim engine from txagent_walk2.py) ----
def decode_fields(fields_ptr, field_count):
    fields = []
    idx = 0
    for fieldno in range(field_count):
        base = fields_ptr + idx * 4
        if not ok_addr(base) or not ok_addr(base + 0x10):
            raise ValueError("fields ptr out of range")
        word0 = rd32(base)
        TB = (word0 >> 8) & 0xFF
        atype = word0 & 3
        TOP16 = (word0 >> 16) & 0xFFFF
        tag_low6 = (word0 >> 2) & 0x3F
        rec = dict(fieldno=fieldno, idx=idx, atype=atype, TB=TB)
        if atype == 0:
            arraySize = 1; tag = tag_low6
            backoffset = (word0 >> 24) & 0xF; dataOffsetRaw = (word0 >> 16) & 0xFF
        elif atype == 2:
            word1 = rd32(base + 4); word2 = rd32(base + 8); word3 = rd32(base + 0xc)
            arraySize = TOP16; tag = u16(tag_low6 | u16((word1 >> 8) << 6))
            backoffset = word1 & 0xFF; dataOffsetRaw = word2
        elif atype == 1:
            word1 = rd32(base + 4)
            arraySize = TOP16 & 0xFFF; tag = u16(tag_low6 | (((word1 >> 0x1c) & 0xF) << 6))
            backoffset = (word0 >> 0x1c) & 0xF; dataOffsetRaw = word1 & 0xFFFF
        else:  # atype == 3
            word1 = rd32(base + 4); word2 = rd32(base + 8)
            _word3 = rd32(base + 0xc); word4 = rd32(base + 0x10)
            arraySize = s16(word4); tag = u16(tag_low6 | u16((word1 >> 8) << 6))
            backoffset = word1 & 0xFF; dataOffsetRaw = word2
        rec.update(tag=tag, arraySize=arraySize, backoffset=backoffset,
                   dataOffsetRaw=dataOffsetRaw, ltype=TB & 0xF, htype=TB & 0x30,
                   ptrclass=TB & 0xC0, is_submsg=(TB & 0xF) in (8, 9))
        fields.append(rec)
        idx += 1 << atype
    return fields

# ---- LTYPE -> proto-ish type name (nanopb PB_LTYPE_*) ----
LTYPE = {
    0x0: "bool", 0x1: "int/enum(varint)", 0x2: "uint(varint)", 0x3: "sint(svarint)",
    0x4: "fixed32/float", 0x5: "fixed64/double", 0x6: "string/bytes(len-delim)",
    0x7: "bytes", 0x8: "submessage", 0x9: "submsg_w_cb", 0xA: "extension", 0xB: "fixed_len_bytes",
}
HTYPE = {0x00: "required/static", 0x10: "optional/singular", 0x20: "repeated", 0x30: "oneof"}

def is_msgdesc(a):
    """True if the 6 words at `a` look like {fields_ptr, submsg_info, 0,0, count, count}."""
    if not ok_addr(a) or not ok_addr(a + 0x14): return False
    fp, sub, z0, z1, c0, c1 = (rd32(a + i * 4) for i in range(6))
    if z0 != 0 or z1 != 0: return False
    if c0 != c1 or not (1 <= c0 <= 200): return False
    if not ok_addr(fp) or fp % 4: return False
    if sub != 0 and (not ok_addr(sub) or sub % 4): return False
    # the field array must decode cleanly to c0 fields with plausible tags
    try:
        fs = decode_fields(fp, c0)
    except Exception:
        return False
    tags = [f["tag"] for f in fs]
    if any(t < 1 or t > 4095 for t in tags): return False
    if len(set(tags)) != len(tags): return False           # unique tags
    return True

def scan_msgdescs():
    found = []
    a = IMG_LO
    while a < IMG_HI - 0x18:
        if is_msgdesc(a):
            found.append(a); a += 0x18            # skip the struct (arrays are contiguous)
        else:
            a += 4
    return found

def msgdesc(a):
    fp, sub, _z0, _z1, c0, _c1 = (rd32(a + i * 4) for i in range(6))
    return dict(addr=a, fields_ptr=fp, submsg_info=sub, field_count=c0,
                fields=decode_fields(fp, c0))

def submsg_children(md):
    """Return {fieldno: child_msgdesc_addr} resolving ltype 8/9 fields via submsg_info,
    indexed by running submessage counter (the verified linkage)."""
    out = {}
    if not md["submsg_info"]: return out
    ctr = 0
    for f in md["fields"]:
        if f["is_submsg"]:
            child = rd32(md["submsg_info"] + ctr * 4)
            out[f["fieldno"]] = child
            ctr += 1
    return out

def try_msgdesc(a):
    """Parse a descriptor at a child address even if it has 0 fields (referenced-as-child
    is strong evidence it is real). Returns md dict or None."""
    if not ok_addr(a) or not ok_addr(a + 0x14): return None
    fp, sub, z0, z1, c0, c1 = (rd32(a + i * 4) for i in range(6))
    if z0 or z1 or c0 != c1 or c0 > 200: return None
    if c0 and (not ok_addr(fp) or fp % 4): return None
    if sub and (not ok_addr(sub) or sub % 4): return None
    try:
        fs = decode_fields(fp, c0) if c0 else []
    except Exception:
        return None
    return dict(addr=a, fields_ptr=fp, submsg_info=sub, field_count=c0, fields=fs)

# ================================ run ================================
print("scanning app rodata for pb_msgdesc_t structs ...")
descs = scan_msgdescs()
print("found %d candidate message descriptors (structural scan)" % len(descs))

# validate the known terminal envelope
TERM = 0x00777840
term_ok = TERM in descs
md_term = msgdesc(TERM) if ok_addr(TERM) else None
print("terminal envelope 0x%08x present in scan: %s ; field_count=%s (expect 25)" % (
    TERM, term_ok, md_term["field_count"] if md_term else "?"))

# build the full table, then close transitively over submsg children (picks up 0-field msgs)
all_md = {a: msgdesc(a) for a in descs}
work = list(all_md)
while work:
    a = work.pop()
    for ca in submsg_children(all_md[a]).values():
        if ca not in all_md:
            m = try_msgdesc(ca)
            if m: all_md[ca] = m; work.append(ca)
total_fields = sum(m["field_count"] for m in all_md.values())
print("total messages (after transitive closure): %d, total fields: %d" % (len(all_md), total_fields))

# roots = not referenced as any message's child
child_addrs = set()
for m in all_md.values():
    child_addrs |= set(submsg_children(m).values())
roots = [a for a in all_md if a not in child_addrs]
still_dangling = sorted(child_addrs - set(all_md))
print("root (top-level) messages: %d ; child-referenced: %d ; still-dangling links: %d" % (
    len(roots), len(child_addrs & set(all_md)), len(still_dangling)))

# roots summary: oneof-envelopes (module dispatch roots) vs plain
print("\n--- ROOT messages (field_count, #oneof-submsg fields) ---")
for a in sorted(roots, key=lambda x: -all_md[x]["field_count"]):
    m = all_md[a]
    noneof = sum(1 for f in m["fields"] if f["htype"] == 0x30 and f["is_submsg"])
    kind = "ENVELOPE(oneof x%d)" % noneof if noneof >= 3 else "msg"
    print("  0x%08x  fields=%2d  %s" % (a, m["field_count"], kind))

json.dump({hex(a): {k: (v if not isinstance(v, list) else v) for k, v in m.items() if k != "fields"}
           | {"fields": m["fields"], "children": {str(k): hex(v) for k, v in submsg_children(m).items()}}
           for a, m in all_md.items()},
          open("docs/pb_schema.json", "w"), indent=1)
print("wrote pb_schema.json")

# sample: dump the terminal envelope + 3 other messages
def dump(a, name=""):
    m = all_md[a]; ch = submsg_children(m)
    print("\nmsg @0x%08x  fields=%d  submsg_info=0x%08x %s" % (a, m["field_count"], m["submsg_info"], name))
    for f in m["fields"]:
        c = "  -> 0x%08x" % ch[f["fieldno"]] if f["fieldno"] in ch else ""
        print("   tag=%-3d %-18s %-16s arr=%d%s" % (
            f["tag"], LTYPE.get(f["ltype"], "L%x" % f["ltype"]), HTYPE.get(f["htype"], "H%x" % f["htype"]),
            f["arraySize"], c))
if term_ok: dump(TERM, "(TERMINAL ENVELOPE)")

# ---- known names (from docs/terminal-protocol.md verified table + log-string _tag idents) ----
# terminal envelope oneof children, by wire tag -> name (docs table, hardware/emu verified)
TERM_TAG_NAME = {3:"mode_sync",4:"host_status",5:"asr_result",6:"session_status",
    7:"agent_content",8:"query",14:"reset",16:"session_list",21:"session_id_changed",
    15:"error_or_switch_or_new_result",17:"error_or_switch_or_new_result",
    23:"error_or_switch_or_new_result"}
names = {}   # addr -> name
if term_ok:
    ch = submsg_children(all_md[TERM])
    for f in all_md[TERM]["fields"]:
        if f["fieldno"] in ch and f["tag"] in TERM_TAG_NAME:
            names[ch[f["fieldno"]]] = "Terminal_" + TERM_TAG_NAME[f["tag"]]
names[TERM] = "TerminalEnvelope"

# ---- emit a .proto-ish text dump ----
def tname(f, ch, msgname):
    if f["fieldno"] in ch:
        c = ch[f["fieldno"]]
        return names.get(c, "M_%06x" % (c & 0xffffff))
    return {0x0:"bool",0x1:"int32",0x2:"uint32",0x3:"sint32",0x4:"fixed32",0x5:"fixed64",
            0x6:"string_or_bytes",0x7:"bytes",0xB:"fixed_bytes"}.get(f["ltype"], "L%x"%f["ltype"])

out = []
out.append("// Auto-extracted nanopb schema from g2_2.2.4.34.bin (structure only; names known where noted)")
out.append("// %d messages, %d fields, %d roots (%d oneof-envelopes)\n" % (
    len(all_md), total_fields, len(roots), sum(1 for a in roots
    if sum(1 for f in all_md[a]['fields'] if f['htype']==0x30 and f['is_submsg'])>=3)))
for a in sorted(all_md, key=lambda x: (x not in roots, x)):
    m = all_md[a]; ch = submsg_children(m)
    nm = names.get(a, "M_%06x" % (a & 0xffffff))
    out.append("message %s {   // @0x%08x  %s" % (nm, a, "ROOT" if a in roots else ""))
    for f in m["fields"]:
        rep = "repeated " if f["htype"] == 0x20 else ("oneof " if f["htype"] == 0x30 else "")
        out.append("  %s%s field%d = %d;%s" % (
            rep, tname(f, ch, nm), f["tag"], f["tag"],
            "  // array[%d]" % f["arraySize"] if f["arraySize"] > 1 else ""))
    out.append("}")
open("docs/pb_schema.proto", "w").write("\n".join(out))
print("\nwrote g2_schema.proto (%d lines)" % len(out))
