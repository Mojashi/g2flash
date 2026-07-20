# -*- coding: utf-8 -*-
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
mem = currentProgram.getMemory()
rm = currentProgram.getReferenceManager()
di = DecompInterface(); di.openProgram(currentProgram); mon = ConsoleTaskMonitor()
def A(h): return af.getAddress(h)
def rd32(a):
    x = A(a)
    return ((mem.getByte(x)&0xff)|((mem.getByte(x.add(1))&0xff)<<8)|((mem.getByte(x.add(2))&0xff)<<16)|((mem.getByte(x.add(3))&0xff)<<24))

# full health RX handler
f = fm.getFunctionContaining(A("0x00578d88"))
res = di.decompileFunction(f, 60, mon)
print("===== %s =====" % f.getName())
print(res.getDecompiledFunction().getC())
# what do the DAT_ pointer globals near it hold?
for g in ("0x005795e4","0x005795e8"):
    try: print("%s -> 0x%08x" % (g, rd32(g)))
    except Exception as e: print("%s err %s" % (g, e))
# the decode function 0x4aa564: signature + how many callers
d = fm.getFunctionContaining(A("0x004aa564"))
if d:
    print("\ndecode fn:", d.getName(), "@", d.getEntryPoint(), "callers=", len(list(rm.getReferencesTo(d.getEntryPoint()))))
