# -*- coding: utf-8 -*-
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
fm=currentProgram.getFunctionManager(); af=currentProgram.getAddressFactory(); rm=currentProgram.getReferenceManager()
listing=currentProgram.getListing()
dec=DecompInterface(); dec.openProgram(currentProgram); mon=ConsoleTaskMonitor()
def A(h): return af.getAddress(h)

# 1) The callback table at 0x4bbeb8..0x4bbed4: decompile the 3 functions alongside DRV_IMUDataParserCallback
for addr in ["0x4bbc68","0x4bbca2","0x4a7124"]:
    f=fm.getFunctionAt(A(addr))
    if f is None: f=fm.getFunctionContaining(A(addr))
    if f is None: print("no fn @ %s"%addr); continue
    res=dec.decompileFunction(f,90,mon)
    print("\n===== %s @%s ====="%(f.getName(),f.getEntryPoint()))
    print(res.getDecompiledFunction().getC()[:2000])

# 2) Who references the callback table itself (0x4bbeb8)?
# The table is the sensor_hub driver's static init struct. Find what loads it.
print("\n=== refs to table region 0x4bbeb8..0x4bbed8 ===")
for off in range(0, 0x20, 4):
    a = A("0x%x" % (0x4bbeb8 + off))
    refs = list(rm.getReferencesTo(a))
    if refs:
        for r in refs:
            f = fm.getFunctionContaining(r.getFromAddress())
            print("  0x%x: ref from %s (%s)" % (0x4bbeb8+off, r.getFromAddress(), f.getName() if f else "?"))

# 3) What does HUB_Open(2) actually DO inside the sensor hub? Decompile the message handler
# that processes HUB_Open's message (the queue consumer).
print("\n=== HUB message queue consumer ===")
# DAT_004bf584 + 0xc = the queue handle. Find who reads from this queue.
# The sensor_hub module tag funcs:
for f in fm.getFunctions(True):
    c = listing.getComment(3, f.getEntryPoint())
    if c and "sensor_hub" in c and "thread" in f.getName().lower():
        res=dec.decompileFunction(f,90,mon)
        print("\n===== %s @%s ====="%(f.getName(),f.getEntryPoint()))
        print(res.getDecompiledFunction().getC()[:2500])
        break

# 4) The key question: who sets data[0] bit4 and bit5? Search for functions that configure
# the IMU chip mode. Look for DRV_IMU* functions we haven't decompiled yet.
print("\n=== all DRV_IMU* functions ===")
for f in fm.getFunctions(True):
    if f.getName().startswith("DRV_IMU"):
        print("  0x%x %s" % (f.getEntryPoint().getOffset(), f.getName()))
