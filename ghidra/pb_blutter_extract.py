#!/usr/bin/env python3
"""
Extract the authoritative app-side protobuf schema from Blutter's asm dump.

Each generated <service>.pb.dart has, per message class, a `static BuilderInfo _i()` whose
disassembly builds the field table with calls to protobuf BuilderInfo::a / ::e / ::p / ::pc
/ ::aOM / ::aQM / ::m / ... . Right before each such call the asm sets up:
    r0 = <TAG>              (mov x0, #tag)
    r16 = "<fieldName>"     (string const)   <-- names are NOT omitted in this build!
    (and a TypeArguments <Type> or Instance_<enum> for submessage / enum fields)
We recover (tag, name, method, type) per field, grouped by message class.
Output: pb_app_schema.json  { service_file: { MsgName: [ {tag,name,method,type} ] } }
"""
import os, re, json, glob

ASM = "/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/blutter_ws/blutter_out/asm/even_connect/g2/proto/generated"

# BuilderInfo field-adder methods (exclude the BuilderInfo constructor itself)
ADDERS = {'a','aOM','aOS','aOB','aQM','aQS','aInt64','aInt32','aUint32','aUint64','aSint32',
          'aSint64','aFixed32','aFixed64','aFloat','aDouble','aBool','aString','aBytes',
          'e','p','pc','pp','m','aQB','aOl','auint32','aint64','aInt64OrDefault'}
# rough proto-type hint from method + field-flags
def type_hint(method, typearg):
    if method in ('aOM','m'): return 'msg:%s' % (typearg or '?')     # submessage (optional/oneof)
    if method in ('aQM','pc'): return 'repeated_msg:%s' % (typearg or '?')
    if method == 'e': return 'enum:%s' % (typearg or '?')
    if method == 'p': return 'repeated:%s' % (typearg or 'scalar')
    if method in ('aOS','aString'): return 'string'
    if method in ('aOB','aBytes'): return 'bytes'
    return method  # generic scalar 'a' etc. (wire type is on the firmware side anyway)

RE_CLASS = re.compile(r'^class (\w+)')
RE_INT   = re.compile(r'r0 = (\d+)\s*$')
RE_STR   = re.compile(r'r16 = "([^"]+)"')
RE_TYPEA = re.compile(r'TypeArguments: <([^>]+)>')
RE_INST  = re.compile(r'Instance_(\w+)')
RE_CALL  = re.compile(r'BuilderInfo::(\w+)\b')
RE_FIELD_I = re.compile(r'Field <(\w+)\._i@')
RE_CREATE  = re.compile(r'(\w+)::create\b')

def parse_file(path):
    msgs = {}                      # MsgName -> list of fields
    cur_class = None
    cur_i_msg = None               # message whose _i() we're inside (from Field <X._i@>)
    # sliding recent tokens; the field's (tag,type) are FROZEN when its name string appears
    # (the 0x8000 field-flag int comes AFTER the name, so freezing avoids clobbering the tag)
    last_int = None; last_type = None
    p_tag = None; p_name = None; p_type = None
    for line in open(path, encoding='utf-8', errors='replace'):
        mc = RE_CLASS.match(line.strip())
        if mc and mc.group(1) != '::':
            cur_class = mc.group(1); last_int=last_type=None
        if 'BuilderInfo _i()' in line or '_i() {' in line:
            cur_i_msg = None; last_int=last_type=None
        mf = RE_FIELD_I.search(line)
        if mf: cur_i_msg = mf.group(1)
        mi = RE_INT.search(line)
        if mi:
            v = int(mi.group(1))
            if 0 < v < 2048: last_int = v               # plausible small proto tag (this protocol)
        mt = RE_TYPEA.search(line)
        if mt: last_type = mt.group(1)
        else:
            mins = RE_INST.search(line)
            if mins: last_type = mins.group(1)
        ms = RE_STR.search(line)
        if ms:                                          # FREEZE tag+type at the field name
            p_tag = last_int; p_name = ms.group(1); p_type = last_type
        mcall = RE_CALL.search(line)
        if mcall:
            meth = mcall.group(1)
            if meth in ADDERS and p_tag is not None and p_name is not None:
                name = cur_i_msg or cur_class or '?'
                msgs.setdefault(name, [])
                if not any(f['tag'] == p_tag for f in msgs[name]):
                    msgs[name].append(dict(tag=p_tag, name=p_name, method=meth,
                                           type=type_hint(meth, p_type)))
            last_int = last_type = None; p_tag = p_name = p_type = None
    # sort fields by tag
    for k in msgs: msgs[k].sort(key=lambda f: f['tag'])
    return msgs

allsvc = {}
for path in sorted(glob.glob(ASM + '/*/*.pb.dart')):
    svc = os.path.basename(path).replace('.pb.dart','')
    m = parse_file(path)
    if m: allsvc[svc] = m

json.dump(allsvc, open('/private/tmp/claude-501/-Users-mojashi-repos-odd/70e4d562-4b1b-41ba-9eac-bd869645bc38/scratchpad/pb_app_schema.json','w'), indent=1)

# summary
nmsg = sum(len(v) for v in allsvc.values())
nfld = sum(len(f) for v in allsvc.values() for f in v.values())
print("services(files): %d  messages: %d  fields: %d" % (len(allsvc), nmsg, nfld))
print("\n=== per-service message counts ===")
for svc in sorted(allsvc): print("  %-22s %d messages" % (svc, len(allsvc[svc])))

# VALIDATE against terminal (we know tag3=mode_sync,7=agent_content,8=query,16=session_list,21=session_id_changed)
print("\n=== VALIDATION: terminal envelope (the DataPackage message) ===")
term = allsvc.get('terminal', {})
# find the envelope msg = the one with the most fields (the DataPackage)
if term:
    env = max(term.items(), key=lambda kv: len(kv[1]))
    print("  envelope msg = %s (%d fields)" % (env[0], len(env[1])))
    for f in env[1][:26]:
        print("    tag%-3d %-26s %s" % (f['tag'], f['name'], f['type']))
