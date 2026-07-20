# -*- coding: utf-8 -*-
# Ghidra headless: retype pb handler payload params to their firmware-exact /pb message struct*,
# from the wf_pb_decode workflow mappings [{addr, param, struct}]. @category CFW
import json
from ghidra.program.model.data import PointerDataType
from ghidra.program.model.symbol import SourceType
from java.lang import Throwable

fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
dtm = currentProgram.getDataTypeManager()
def A(h): return af.getAddress(h if str(h).startswith("0x") else "0x" + h)

args = getScriptArgs()
maps = json.load(open(args[0]))
applied = 0; skip_nofn = 0; skip_nostruct = 0; skip_noparam = 0
for m in maps:
    sdt = dtm.getDataType("/pb/" + m["struct"])
    if sdt is None:
        skip_nostruct += 1; continue
    f = fm.getFunctionAt(A(m["addr"]))
    if f is None:
        skip_nofn += 1; continue
    target = None
    for p in f.getParameters():
        if p.getName() == m["param"]:
            target = p; break
    if target is None:
        skip_noparam += 1
        print("  no param '%s' in %s" % (m["param"], f.getName())); continue
    try:
        target.setDataType(PointerDataType(sdt), SourceType.USER_DEFINED)
        applied += 1
    except Throwable as e:
        print("  set fail %s.%s: %s" % (f.getName(), m["param"], e))
print("apply_pb_decode: typed %d payload params (skip: %d no-fn, %d no-struct, %d no-param)"
      % (applied, skip_nofn, skip_nostruct, skip_noparam))
