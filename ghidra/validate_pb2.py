# -*- coding: utf-8 -*-
# Ghidra headless: retype the EvenAI encode buffer global to EvenAIDataPackage* and re-decompile
# 0x508942 to demonstrate the pb structs resolve raw offsets to named fields. @category CFW
from ghidra.app.decompiler import DecompInterface
from ghidra.util.task import ConsoleTaskMonitor
from ghidra.program.model.data import PointerDataType
from ghidra.program.model.symbol import SourceType

dtm = currentProgram.getDataTypeManager()
af = currentProgram.getAddressFactory()
fm = currentProgram.getFunctionManager()
listing = currentProgram.getListing()
def A(h): return af.getAddress(h)

evenai = dtm.getDataType("/pb/EvenAIDataPackage")
print("EvenAIDataPackage len =", evenai.getLength())

# DAT_00508f90 holds the pointer to the 0x20c buffer; type it as EvenAIDataPackage*
g = A("0x00508f90")
listing.clearCodeUnits(g, g, False)
listing.createData(g, PointerDataType(evenai))
print("typed global 0x508f90 as EvenAIDataPackage*")

dec = DecompInterface(); dec.openProgram(currentProgram); mon = ConsoleTaskMonitor()
f = fm.getFunctionContaining(A("0x00508942"))
res = dec.decompileFunction(f, 60, mon)
code = res.getDecompiledFunction().getC()
# print just the assignment region that shows field names
lines = code.split("\n")
for i, ln in enumerate(lines):
    if "0x20c" in ln or "->" in ln or "commandId" in ln or "which_" in ln or "magicRandom" in ln:
        print("  %s" % ln.strip())
