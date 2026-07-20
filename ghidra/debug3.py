fm = currentProgram.getFunctionManager()
af = currentProgram.getAddressFactory()
# Check both even and odd addresses
for a in [0x43d514, 0x43d515, 0x43ce46, 0x43ce47]:
    addr = af.getAddress("0x%x" % a)
    f = fm.getFunctionAt(addr)
    fc = fm.getFunctionContaining(addr)
    print("0x%x: at=%s  containing=%s" % (a, f.getName() if f else "NONE", fc.getName() if fc else "NONE"))
# list functions near 0x43d514
for f in fm.getFunctions(af.getAddress("0x43d500"), True):
    if f.getEntryPoint().getOffset() > 0x43d520: break
    print("  nearby: %s @ %s" % (f.getName(), f.getEntryPoint()))
