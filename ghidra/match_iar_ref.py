# -*- coding: utf-8 -*-
# Match FW functions against IAR-compiled BLE reference binary.
# Since both are IAR, we can try exact byte matching first, then BSim.
#
# @category G2

import ghidra.features.bsim.query.FunctionDatabase as FunctionDatabase
import ghidra.features.bsim.query.GenSignatures as GenSignatures
import generic.lsh.vector.VectorCompare as VectorCompare
from ghidra.program.model.symbol import SourceType

program = currentProgram
fm = program.getFunctionManager()

# Open IAR BLE reference
project = state.getProject()
ref_file = None
for f in project.getProjectData().getRootFolder().getFiles():
    if 'ble_apollo510_iar' in f.getName():
        ref_file = f
        break

if not ref_file:
    print("match_iar: ERROR - BLE reference not found")
    import sys
    sys.exit(1)

ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()

# Count ref symbols
ref_funcs = {}
for func in ref_fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_') and not n.startswith('.') and '??' not in n:
        ref_funcs[n] = func

print("match_iar: IAR reference has %d named functions" % len(ref_funcs))

# Already named in FW
already = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if not n.startswith('FUN_'):
        already.add(n)

# Filter ref to only unmatched
unmatched_ref = {n: f for n, f in ref_funcs.items() if n not in already}
print("match_iar: %d unmatched ref functions to match" % len(unmatched_ref))

# ---- Method 1: Exact function bytes match ----
print("match_iar: Method 1 - Exact bytes match...")

def get_func_bytes(prog, func):
    body = func.getBody()
    mem = prog.getMemory()
    result = bytearray()
    ranges = body.getAddressRanges()
    while ranges.hasNext():
        r = ranges.next()
        length = int(r.getLength())
        buf = java.lang.reflect.Array.newInstance(java.lang.Byte.TYPE, length)
        try:
            mem.getBytes(r.getMinAddress(), buf)
            for b in buf:
                result.append(b & 0xFF)
        except:
            pass
    return bytes(result)

# Build hash table of ref function bytes
ref_hashes = {}
for name, func in unmatched_ref.items():
    b = get_func_bytes(ref_prog, func)
    if len(b) >= 4:
        h = hash(b)
        ref_hashes[h] = (name, b, func.getBody().getNumAddresses())

print("match_iar:   %d ref function hashes" % len(ref_hashes))

# Search FW functions for exact matches
exact_matches = []
for func in fm.getFunctions(True):
    if not func.getName().startswith('FUN_'):
        continue
    b = get_func_bytes(program, func)
    if len(b) < 4:
        continue
    h = hash(b)
    if h in ref_hashes:
        ref_name, ref_bytes, ref_size = ref_hashes[h]
        if b == ref_bytes:  # verify (hash collision check)
            exact_matches.append((func.getName(), ref_name, len(b)))

print("match_iar:   Exact byte matches: %d" % len(exact_matches))
for fw_name, ref_name, size in exact_matches[:20]:
    print("match_iar:     %s -> %s (%dB exact)" % (fw_name, ref_name, size))

# ---- Method 2: BSim for remaining ----
print("\nMatch_iar: Method 2 - BSim for non-exact matches...")

vectorFactory = FunctionDatabase.generateLSHVectorFactory()
config = FunctionDatabase.loadConfigurationTemplate("medium_32")
vectorFactory.set(config.weightfactory, config.idflookup, config.info.settings)

# Ref sigs
gensig_ref = GenSignatures(True)
gensig_ref.setVectorFactory(vectorFactory)
repo = "ghidra://localhost/" + state.getProject().getName()
gensig_ref.openProgram(ref_prog, None, None, None, repo, GenSignatures.getPathFromDomainFile(ref_prog))
gensig_ref.scanFunctions(ref_fm.getFunctions(True), ref_fm.getFunctionCount(), monitor)
ref_mgr = gensig_ref.getDescriptionManager()
ref_vecs = {}
di = ref_mgr.listAllFunctions()
while di.hasNext():
    d = di.next()
    n = d.getFunctionName()
    if n in unmatched_ref and n not in set(m[1] for m in exact_matches):
        sr = d.getSignatureRecord()
        if sr:
            v = sr.getLSHVector()
            if v:
                ref_vecs[n] = v

# FW sigs
gensig_fw = GenSignatures(True)
gensig_fw.setVectorFactory(vectorFactory)
gensig_fw.openProgram(program, None, None, None, repo, GenSignatures.getPathFromDomainFile(program))
gensig_fw.scanFunctions(fm.getFunctions(True), fm.getFunctionCount(), monitor)
fw_mgr = gensig_fw.getDescriptionManager()
fw_vecs = {}
di2 = fw_mgr.listAllFunctions()
while di2.hasNext():
    d = di2.next()
    n = d.getFunctionName()
    if n.startswith('FUN_'):
        sr = d.getSignatureRecord()
        if sr:
            v = sr.getLSHVector()
            if v:
                fw_vecs[n] = v

print("match_iar:   %d ref BSim vecs, %d FW vecs" % (len(ref_vecs), len(fw_vecs)))

# Match
bsim_matches = []
vc = VectorCompare()
processed = 0
for ref_name, ref_vec in ref_vecs.items():
    processed += 1
    if processed % 50 == 0:
        print("match_iar:   BSim %d/%d..." % (processed, len(ref_vecs)))
    best_sim = 0
    best_fw = None
    for fw_name, fw_vec in fw_vecs.items():
        sim = ref_vec.compare(fw_vec, vc)
        if sim > best_sim:
            best_sim = sim
            best_fw = fw_name
    if best_fw and best_sim >= 0.7:
        bsim_matches.append((best_fw, ref_name, best_sim))

print("match_iar:   BSim matches (sim>=0.7): %d" % len(bsim_matches))
for fw_name, ref_name, sim in sorted(bsim_matches, key=lambda x: -x[2])[:20]:
    print("match_iar:     sim=%.3f %s -> %s" % (sim, fw_name, ref_name))

# ---- Apply ----
print("\nmatch_iar: Applying...")
applied = 0

# Build lookup
fw_by_name = {}
for f in fm.getFunctions(True):
    fw_by_name[f.getName()] = f

# Apply exact matches
for fw_name, ref_name, size in exact_matches:
    func = fw_by_name.get(fw_name)
    if func and func.getName().startswith('FUN_'):
        func.setName(ref_name, SourceType.ANALYSIS)
        func.setComment("IAR exact byte match (%dB)" % size)
        applied += 1

# Apply BSim matches (dedup)
used = set(m[1] for m in exact_matches)
for fw_name, ref_name, sim in sorted(bsim_matches, key=lambda x: -x[2]):
    if ref_name in used:
        continue
    func = fw_by_name.get(fw_name)
    if func and func.getName().startswith('FUN_'):
        func.setName(ref_name, SourceType.ANALYSIS)
        func.setComment("IAR BSim match (sim=%.3f)" % sim)
        applied += 1
        used.add(ref_name)

print("match_iar: === DONE: %d applied (exact=%d bsim=%d) ===" %
      (applied, len(exact_matches), len(bsim_matches)))

ref_prog.release(java.lang.Object())
