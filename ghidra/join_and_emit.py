#!/usr/bin/env python3
"""
Produce the authoritative g2 protobuf schema by combining:
  - Blutter app-side extraction (pb_app_schema.json): message NAME + tag + type + submsg,
    the ground-truth reconstructed from libapp.so.
  - firmware-side descriptors (pb_schema.json): the exact wire tags/structure we decode,
    used to CONFIRM which firmware descriptor address is each app message (fingerprint join).

Emits:
  docs/pb_schema_named.proto  — reconstructed .proto (names+tags+types), authoritative.
  docs/pb_firmware_binding.md  — firmware envelope addr -> app service (with match score).
"""
import json, os

SP = "/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad"
REPO = "/Users/mojashi/repos/odd/g2flash"
app = json.load(open(SP + "/pb_app_schema.json"))       # {svc: {MsgName: [{tag,name,method,type}]}}
fw = json.load(open(REPO + "/docs/pb_schema.json"))     # {addr: {fields:[...], children:{fieldno:addr}}}

# ---------- 1) emit reconstructed .proto from Blutter ----------
def proto_type(f):
    t = f["type"]
    if t.startswith("msg:"):          return t[4:]
    if t.startswith("repeated_msg:"): return "repeated " + t[13:]
    if t.startswith("enum:"):         return t[5:]
    if t.startswith("repeated:"):     return "repeated " + (t[9:] if t[9:] != "scalar" else "bytes")
    if t == "string":                 return "string"
    if t == "bytes":                  return "bytes"
    return "uint32"   # generic scalar 'a' (exact int width lives on the firmware/wire side)

lines = ["// Even Realities G2 protobuf schema — reconstructed from libapp.so via Blutter",
         "// (Flutter Dart AOT). Names+tags+types are authoritative (app side). %d services, "
         "%d messages." % (len(app), sum(len(v) for v in app.values())), 'syntax = "proto3";', ""]
for svc in sorted(app):
    lines.append("// ===== service: %s =====" % svc)
    for msg in sorted(app[svc]):
        lines.append("message %s {" % msg)
        for f in app[svc][msg]:
            lines.append("  %s %s = %d;" % (proto_type(f), f["name"], f["tag"]))
        lines.append("}")
    lines.append("")
open(REPO + "/docs/pb_schema_named.proto", "w").write("\n".join(lines))
print("wrote docs/pb_schema_named.proto (%d messages)" % sum(len(v) for v in app.values()))

# ---------- 2) fingerprint-join firmware envelopes to app messages ----------
# FINER fingerprint per tag: 'S' scalar, or 'M<childFieldCount>' for a submessage — the
# child field-count disambiguates same-shaped envelopes (Conversate vs Teleprompt vs ...).
def fw_fp(addr):
    m = fw.get(addr)
    if not m: return {}
    ch = m.get("children", {})
    out = {}
    for f in m["fields"]:
        if f["is_submsg"]:
            caddr = ch.get(str(f["fieldno"]))
            n = len(fw[caddr]["fields"]) if caddr and caddr in fw else -1
            out[f["tag"]] = "M%d" % n
        else:
            out[f["tag"]] = "S"
    return out
def app_fp(fields):
    out = {}
    for f in fields:
        t = f["type"]
        if t.startswith(("msg:", "repeated_msg:")):
            tn = t.split(":", 1)[1]
            child = app_msgs.get(tn)
            n = len(child[1]) if child else -1
            out[f["tag"]] = "M%d" % n
        else:
            out[f["tag"]] = "S"
    return out

# firmware roots (envelopes) = not referenced as a child
child = set()
for a, m in fw.items():
    child |= set(m.get("children", {}).values())
fw_roots = [a for a in fw if a not in child]

# all app messages flat
app_msgs = {}
for svc, mm in app.items():
    for msg, fields in mm.items():
        app_msgs[msg] = (svc, fields)

def score(fwfp, appfp):
    keys = set(fwfp) | set(appfp)
    if not keys: return 0.0
    agree = sum(1 for k in keys if fwfp.get(k) == appfp.get(k))
    return agree / len(keys)

report = ["# Firmware descriptor -> app message binding (fingerprint join)\n",
          "Each firmware envelope descriptor (wire tags we decode) matched to the app-side",
          "message (Blutter names) by tag-structure fingerprint. Score = fraction of tags whose",
          "submessage-vs-scalar shape agrees.\n"]
# Only app messages that look like envelopes (a oneof of >=3 submsg fields) compete for
# the firmware envelopes; precompute their fingerprints.
env_candidates = {m: (svc, f) for m, (svc, f) in app_msgs.items()
                  if sum(1 for x in f if x["type"].startswith(("msg:", "repeated_msg:"))) >= 3}
pairs = []
for addr in fw_roots:
    fwfp = fw_fp(addr)
    if len(fwfp) < 3: continue
    for msg, (svc, fields) in env_candidates.items():
        pairs.append((score(fwfp, app_fp(fields)), len(fields), addr, msg, svc))
pairs.sort(key=lambda p: (-p[0], -p[1]))
bindings = {}; used_msg = set()
for sc, _n, addr, msg, svc in pairs:
    if addr in bindings or msg in used_msg: continue
    bindings[addr] = (msg, svc, sc); used_msg.add(msg)
for addr in sorted(bindings, key=lambda a: -len(fw[a]["fields"])):
    msg, svc, sc = bindings[addr]
    report.append("- **%s** (%d fields) -> `%s` [service %s]  match=%.0f%%" %
                  (addr, len(fw[addr]["fields"]), msg, svc, sc * 100))
open(REPO + "/docs/pb_firmware_binding.md", "w").write("\n".join(report))
print("wrote docs/pb_firmware_binding.md (%d envelope bindings)" % len(bindings))

print("\n=== top firmware<->app bindings ===")
for addr in sorted(bindings, key=lambda a: -bindings[a][2])[:16]:
    msg, svc, sc = bindings[addr]
    print("  %s -> %-24s [%s]  %.0f%%" % (addr, msg, svc, sc * 100))
