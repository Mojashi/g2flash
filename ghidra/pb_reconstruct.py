#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Reconstruct FIRMWARE-EXACT nanopb message structs for g2 fw 2.2.4.34 directly from the
on-device pb_msgdesc_t descriptors (ground truth), and overlay app-side (Blutter) NAMES
propagated transitively through the submessage graph from the confident fingerprint-bound
roots. Emits:
  docs/pb_msgdesc.h   -- human-readable exact C structs (offsets verified by construction)
  pb_layout.json      -- machine-exact per-field layout for the Ghidra apply step

Layout is authoritative from the descriptor: dataOffsetRaw = ABSOLUTE byte offset (proven),
data_size = field byte width, backoffset = delta back to the has_/count/which_ meta field,
htype 0x30 = oneof (members share one union offset), ltype 8/9 = submessage (child via
submsg_info). Every field offset + the struct total are exact; names are best-effort.
"""
import struct, json, re, os

FW = "/Users/mojashi/repos/odd/g2flash/g2_2.2.4.34.bin"
BASE = 0x39E680
IMG_LO = 0x00438000
IMG_HI = 0x0078F188
data = open(FW, "rb").read()
HERE = os.path.dirname(os.path.abspath(__file__))  # g2flash/ghidra/
DOCS = "/Users/mojashi/repos/odd/g2flash/docs"

def ok(a): return IMG_LO <= a < IMG_HI and (a - BASE) < len(data)
def rd32(a): return struct.unpack_from("<I", data, a - BASE)[0]
def u16(x): return x & 0xFFFF
def s16(x):
    x &= 0xFFFF
    return x - 0x10000 if x & 0x8000 else x

# ---------- descriptor field decoder (validated engine + data_size) ----------
def decode_fields(fp, fc):
    fs = []; idx = 0
    for fn in range(fc):
        b = fp + idx * 4
        if not ok(b) or not ok(b + 0x10): raise ValueError("oob")
        w0 = rd32(b); TB = (w0 >> 8) & 0xFF; at = w0 & 3; TOP16 = (w0 >> 16) & 0xFFFF; tl6 = (w0 >> 2) & 0x3F
        if at == 0:
            arr = 1; tag = tl6; bko = (w0 >> 24) & 0xF; off = (w0 >> 16) & 0xFF; ds = (w0 >> 28) & 0xF
        elif at == 1:
            w1 = rd32(b + 4); arr = TOP16 & 0xFFF; tag = u16(tl6 | (((w1 >> 0x1c) & 0xF) << 6))
            bko = (w0 >> 0x1c) & 0xF; off = w1 & 0xFFFF; ds = (w1 >> 16) & 0xFFF
        elif at == 2:
            w1 = rd32(b + 4); w2 = rd32(b + 8); w3 = rd32(b + 0xc)
            arr = TOP16; tag = u16(tl6 | u16((w1 >> 8) << 6)); bko = w1 & 0xFF; off = w2; ds = w3
        else:
            w1 = rd32(b + 4); w2 = rd32(b + 8); w3 = rd32(b + 0xc); w4 = rd32(b + 0x10)
            arr = s16(w4); tag = u16(tl6 | u16((w1 >> 8) << 6)); bko = w1 & 0xFF; off = w2; ds = w3
        fs.append(dict(fn=fn, atype=at, tag=tag, ltype=TB & 0xF, htype=TB & 0x30,
                       ptrclass=TB & 0xC0, arr=arr, off=off, ds=ds, bko=bko))
        idx += 1 << at
    return fs

def try_md(a):
    if not ok(a) or not ok(a + 0x14): return None
    fp, sub, z0, z1, c0, c1 = (rd32(a + i * 4) for i in range(6))
    if z0 or z1 or c0 != c1 or c0 > 200: return None
    if c0 and (not ok(fp) or fp % 4): return None
    if sub and (not ok(sub) or sub % 4): return None
    try:
        fs = decode_fields(fp, c0) if c0 else []
    except Exception:
        return None
    tags = [f["tag"] for f in fs]
    if any(t < 1 or t > 4095 for t in tags) or len(set(tags)) != len(tags): return None
    return dict(addr=a, fields_ptr=fp, submsg_info=sub, field_count=c0, fields=fs)

def is_md(a):
    m = try_md(a)
    return m is not None and m["field_count"] >= 1

def children(md):
    """fieldno -> child descriptor addr for ltype 8/9 fields (running submsg counter)."""
    out = {}
    if not md["submsg_info"]: return out
    c = 0
    for f in md["fields"]:
        if f["ltype"] in (8, 9):
            ca = rd32(md["submsg_info"] + c * 4)
            out[f["fn"]] = ca; c += 1
    return out

# ---------- scan all descriptors + transitive closure over submsg children ----------
print("scanning descriptors ...")
found = []
a = IMG_LO
while a < IMG_HI - 0x18:
    if is_md(a): found.append(a); a += 0x18
    else: a += 4
allmd = {a: try_md(a) for a in found}
work = list(allmd)
while work:
    x = work.pop()
    for ca in children(allmd[x]).values():
        if ca not in allmd:
            m = try_md(ca)
            if m: allmd[ca] = m; work.append(ca)
print("messages: %d" % len(allmd))

# ---------- parse Blutter named proto ----------
proto = open(os.path.join(DOCS, "pb_schema_named.proto")).read()
bl_msgs = {}          # msgname -> {tag: (typename, fieldname, repeated)}
for mm in re.finditer(r'message\s+(\w+)\s*\{([^}]*)\}', proto):
    nm = mm.group(1); body = mm.group(2); fld = {}
    for fm in re.finditer(r'^\s*(repeated\s+)?(\w+)\s+(\w+)\s*=\s*(\d+)\s*;', body, re.M):
        rep = bool(fm.group(1)); typ = fm.group(2); fn = fm.group(3); tag = int(fm.group(4))
        fld[tag] = (typ, fn, rep)
    bl_msgs[nm] = fld
MSGNAMES = set(bl_msgs)   # names that denote submessages (else scalar/enum)
print("blutter messages parsed: %d" % len(bl_msgs))

# ---------- seed confident roots (addr -> blutter msg name), match>=80% from binding ----------
SEED = {
    0x777840: "TerminalDataPackage", 0x772398: "EvenAIDataPackage", 0x772c80: "HealthDataPackage",
    0x774eb8: "OnboardingDataPackage", 0x777510: "TelepromptDataPackage", 0x771300: "DashboardDataPackage",
    0x777fc0: "TranslateDataPackage", 0x772980: "G2SettingPackage", 0x774c30: "NotificationDataPackage",
    0x770d18: "ConversateDataPackage", 0x771858: "DashboardExtPackage", 0x7761a8: "QuicklistDataPackage",
}

def shape_ok(md, bname):
    """light validation: the descriptor's submsg-shaped tags should mostly be message-typed in blutter."""
    bl = bl_msgs.get(bname)
    if bl is None: return False
    agree = tot = 0
    for f in md["fields"]:
        if f["tag"] not in bl: continue
        tot += 1
        btyp = bl[f["tag"]][0]
        is_sub_fw = f["ltype"] in (8, 9)
        is_sub_bl = btyp in MSGNAMES
        if is_sub_fw == is_sub_bl: agree += 1
    return tot == 0 or agree / tot >= 0.6

# ---------- propagate names transitively through submessage graph ----------
name_of = {}      # addr -> blutter msg name
conf = {}         # addr -> 'seed' | 'prop'
for a, nm in SEED.items():
    if a in allmd and shape_ok(allmd[a], nm):
        name_of[a] = nm; conf[a] = "seed"
queue = list(name_of)
while queue:
    a = queue.pop(); md = allmd[a]; bname = name_of[a]; bl = bl_msgs.get(bname, {})
    ch = children(md)
    for f in md["fields"]:
        if f["fn"] not in ch: continue
        ca = ch[f["fn"]]
        if ca not in allmd or ca in name_of: continue
        btyp = bl.get(f["tag"], (None,))[0]
        if btyp in MSGNAMES and shape_ok(allmd[ca], btyp):
            name_of[ca] = btyp; conf[ca] = "prop"; queue.append(ca)
print("named descriptors: %d seed + prop (of %d)" % (len(name_of), len(allmd)))

# ---------- C type mapping ----------
def cscalar(ltype, ds):
    if ltype == 0: return "bool"
    if ltype in (1, 3):   # signed varint / enum
        return {1: "int8_t", 2: "int16_t", 4: "int32_t", 8: "int64_t"}.get(ds, "int32_t")
    if ltype == 2:        # unsigned varint
        return {1: "uint8_t", 2: "uint16_t", 4: "uint32_t", 8: "uint64_t"}.get(ds, "uint32_t")
    if ltype == 4: return "uint32_t"   # fixed32/float
    if ltype == 5: return "uint64_t"   # fixed64/double
    return None

# ---------- build per-message exact layout ----------
def field_display_name(md_name, tag, ltype):
    bl = bl_msgs.get(md_name, {})
    if tag in bl: return bl[tag][1]
    base = {0: "b", 1: "i", 2: "u", 3: "s", 4: "f32", 5: "f64", 6: "str", 7: "bytes",
            8: "msg", 9: "msg", 0xB: "fbytes"}.get(ltype, "f")
    return "%s_tag%d" % (base, tag)

def struct_name(a):
    if a in name_of: return name_of[a]
    return "pb_%06x" % (a & 0xFFFFFF)

def build_layout(a):
    md = allmd[a]; nm = name_of.get(a); ch = children(md)
    fs = sorted(md["fields"], key=lambda f: (f["off"], f["tag"]))
    # distinct value offsets in order -> for span (gap to next distinct offset)
    distinct = sorted(set(f["off"] for f in fs))
    nextoff = {distinct[i]: (distinct[i + 1] if i + 1 < len(distinct) else None) for i in range(len(distinct))}
    # group oneof members by shared offset
    out_fields = []   # list of dicts for json/h
    metas = {}        # offset -> meta field dict (has_/count/which_), dedup
    # precompute last-field span end for total size
    total = 0
    byoff = {}
    for f in fs: byoff.setdefault(f["off"], []).append(f)
    for off in distinct:
        grp = byoff[off]
        nx = nextoff[off]
        is_oneof = any(g["htype"] == 0x30 for g in grp)
        # meta (has_/count/which_) from backoffset (shared within group)
        bko = grp[0]["bko"]
        if bko:
            moff = off - bko
            if grp[0]["htype"] == 0x30:
                metas[moff] = dict(name="which_" + (nm or struct_name(a)), off=moff, size=2, kind="which", ctype="uint16_t")
            elif grp[0]["htype"] == 0x20:
                fn0 = field_display_name(nm, grp[0]["tag"], grp[0]["ltype"])
                metas[moff] = dict(name=fn0 + "_count", off=moff, size=2, kind="count", ctype="uint16_t")
            else:
                fn0 = field_display_name(nm, grp[0]["tag"], grp[0]["ltype"])
                metas[moff] = dict(name="has_" + fn0, off=moff, size=1, kind="has", ctype="bool")
        # span of this value slot
        span = (nx - off) if nx is not None else max(g["ds"] for g in grp)
        if is_oneof:
            members = []
            for g in grp:
                cnm = struct_name(ch[g["fn"]]) if g["fn"] in ch else None
                members.append(dict(tag=g["tag"], name=field_display_name(nm, g["tag"], g["ltype"]),
                                    ctype=cnm, ds=g["ds"], ltype=g["ltype"],
                                    ptr=(g["ptrclass"] != 0), child=(hex(ch[g["fn"]]) if g["fn"] in ch else None)))
            out_fields.append(dict(kind="oneof", off=off, span=span,
                                   which_name="which_" + (nm or struct_name(a)), members=members))
            total = max(total, off + span)
        else:
            g = grp[0]
            rep = g["htype"] == 0x20
            ptr = g["ptrclass"] != 0
            if g["ltype"] in (8, 9):
                ctype = struct_name(ch[g["fn"]]) if g["fn"] in ch else "void"
                kind = "submsg"
            elif g["ltype"] in (6,):
                ctype = "char"; kind = "string"
            elif g["ltype"] in (7, 0xB):
                ctype = "uint8_t"; kind = "bytes"
            else:
                ctype = cscalar(g["ltype"], g["ds"]) or "uint32_t"; kind = "scalar"
            # true byte footprint: repeated-static consumes element_size * count (the gap-to-next
            # heuristic undersizes a repeated field that sits last, where span is just one element).
            foot = (g["ds"] * max(1, g["arr"])) if rep else span
            out_fields.append(dict(kind=kind, off=off, span=span, tag=g["tag"],
                                   name=field_display_name(nm, g["tag"], g["ltype"]),
                                   ctype=ctype, ptr=ptr, rep=rep, arr=g["arr"], ds=g["ds"],
                                   ltype=g["ltype"], child=(hex(ch[g["fn"]]) if g["fn"] in ch else None)))
            total = max(total, off + foot)
    # raw_end = last byte consumed (NO alignment rounding here; final size fixed in the post-pass,
    # because a submessage's true sizeof is the data_size its PARENT records for the field).
    metal = sorted(metas.values(), key=lambda m: m["off"])
    raw_end = max(total, max((m["off"] + m["size"] for m in metal), default=0))
    return dict(addr=hex(a), name=struct_name(a), blutter=nm, conf=conf.get(a, "struct"),
                raw_end=raw_end, total=raw_end, metas=metal, fields=out_fields, field_count=md["field_count"])

layouts = {hex(a): build_layout(a) for a in allmd}

# ---- fix struct sizes: nanopb sizeof(child) == the data_size the PARENT records for that
#      submessage field (ground truth). Use it as the embedded size; round root structs (never
#      embedded) up to their own natural alignment. This makes embedding overlap-free. ----
embed = {}
def note(childhex, ds):
    if childhex and ds:
        if childhex in embed and embed[childhex] != ds:
            print("WARN size mismatch %s: %d vs %d" % (childhex, embed[childhex], ds))
        embed[childhex] = max(embed.get(childhex, 0), ds)
for L in layouts.values():
    for f in L["fields"]:
        if f["kind"] == "oneof":
            for mem in f["members"]:
                if mem["child"]: note(mem["child"], mem["ds"])
        elif f["kind"] == "submsg" and f["child"]:
            note(f["child"], f["ds"])
AL = {"bool":1,"char":1,"int8_t":1,"uint8_t":1,"int16_t":2,"uint16_t":2,
      "int32_t":4,"uint32_t":4,"int64_t":8,"uint64_t":8}
_alc = {}
def salign(hx):
    if hx in _alc: return _alc[hx]
    _alc[hx] = 1                       # cycle guard (embed graph is a DAG, pointers break cycles)
    L = layouts.get(hx)
    if not L: return 1
    a = 1
    for m in L["metas"]: a = max(a, m["size"])
    for f in L["fields"]:
        if f["kind"] == "oneof":
            for mem in f["members"]:
                a = max(a, 4 if mem["ptr"] else (salign(mem["child"]) if mem["child"] else AL.get(mem["ctype"], 4)))
        elif f["ptr"]: a = max(a, 4)
        elif f["kind"] == "submsg": a = max(a, salign(f["child"]) if f["child"] else 4)
        elif f["kind"] in ("string", "bytes"): a = max(a, 1)
        else: a = max(a, AL.get(f["ctype"], 4))
    _alc[hx] = a; return a
for hx, L in layouts.items():
    if hx in embed:
        L["total"] = max(embed[hx], L["raw_end"])
        if embed[hx] < L["raw_end"]:
            print("WARN %s parent-size %d < raw_end %d" % (L["name"], embed[hx], L["raw_end"]))
    else:
        al = salign(hx)
        L["total"] = (L["raw_end"] + al - 1) & ~(al - 1)
json.dump(layouts, open(os.path.join(HERE, "pb_layout.json"), "w"), indent=1)
named = sum(1 for L in layouts.values() if L["blutter"])
print("wrote pb_layout.json (%d msgs, %d named)" % (len(layouts), named))

# ---------- emit human-readable exact C header ----------
def emit_h():
    o = []
    o.append("// FIRMWARE-EXACT nanopb message structs for g2 fw 2.2.4.34")
    o.append("// Generated from on-device pb_msgdesc_t descriptors (offsets/sizes are GROUND TRUTH).")
    o.append("// Names overlaid from Blutter app proto, propagated through the submessage graph.")
    o.append("// conf: seed=fingerprint-bound root, prop=name-propagated, struct=layout-only (pb_<addr>).")
    o.append("// %d messages, %d named.\n" % (len(layouts), named))
    o.append("#include <stdint.h>\n#include <stdbool.h>\ntypedef uint16_t pb_size_t;\n")
    # each struct is created at its exact total size, so embedding order does not matter.
    for L in sorted(layouts.values(), key=lambda x: x["addr"]):
        c = " [%s]" % L["conf"]
        o.append("typedef struct %s {   // @%s  fields=%d  size=%d%s" % (
            L["name"], L["addr"], L["field_count"], L["total"], c))
        rows = []
        for m in L["metas"]:
            rows.append((m["off"], "  %-11s %s;" % (m["ctype"], m["name"]), ""))
        for f in L["fields"]:
            if f["kind"] == "oneof":
                inner = ["    %-22s %s;%s" % (
                    (mem["ctype"] + " *") if (mem["ctype"] and mem["ptr"]) else (mem["ctype"] or "uint32_t"),
                    mem["name"], "  // tag %d" % mem["tag"]) for mem in f["members"]]
                blk = "  union {\n" + "\n".join(inner) + "\n  } u;"
                rows.append((f["off"], blk, "  // oneof @off %d, size %d" % (f["off"], f["span"])))
            else:
                t = f["ctype"]
                if f["ptr"]: decl = "%s *%s" % (t, f["name"])
                elif f["kind"] == "string": decl = "char %s[%d]" % (f["name"], f["ds"])
                elif f["kind"] == "bytes": decl = "uint8_t %s[%d]" % (f["name"], f["ds"])
                elif f["rep"]: decl = "%s %s[%d]" % (t, f["name"], f["arr"])
                elif f["kind"] == "submsg": decl = "%s %s" % (t, f["name"])
                else: decl = "%s %s" % (t, f["name"])
                cm = "  // tag %d%s" % (f["tag"], " rep[%d]" % f["arr"] if f["rep"] else "")
                rows.append((f["off"], "  %s;" % decl, cm))
        for off, decl, cm in sorted(rows, key=lambda r: r[0]):
            o.append("%-44s // @%d%s" % (decl, off, cm))
        o.append("} %s;\n" % L["name"])
    return "\n".join(o)

open(os.path.join(DOCS, "pb_msgdesc.h"), "w").write(emit_h())
print("wrote docs/pb_msgdesc.h")

# ---------- sanity dumps ----------
for a in (0x772c80, 0x777840, 0x772398):
    if hex(a) in layouts:
        L = layouts[hex(a)]
        print("\n== %s  %s  size=%d  conf=%s" % (L["addr"], L["name"], L["total"], L["conf"]))
        for m in L["metas"]: print("   meta @%-3d %-8s %s" % (m["off"], m["ctype"], m["name"]))
        for f in L["fields"]:
            if f["kind"] == "oneof":
                print("   @%-3d oneof (%d members): %s" % (f["off"], len(f["members"]),
                      ", ".join("%s:%s" % (x["name"], x["ctype"]) for x in f["members"])))
            else:
                print("   @%-3d tag%-3d %-10s %s%s" % (f["off"], f["tag"], f["kind"], f["ctype"],
                      "*" if f["ptr"] else ""))
