# -*- coding: utf-8 -*-
# Ghidra headless script: structural matching of FW functions against LVGL reference .o
#
# Opens the reference program (lvgl_ref.o) from the same project,
# computes function fingerprints (mnemonic sequence hash, basic block count,
# call count, function size), and matches against unnamed FW functions.
#
# This works across compilers (IAR vs GCC) because it uses structural
# similarity rather than exact byte matching.
#
# @category G2
# @author Claude

import hashlib
from collections import defaultdict
from ghidra.program.model.symbol import SourceType
from ghidra.program.model.listing import CodeUnit
from ghidra.program.model.block import BasicBlockModel

program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()

# ---- Step 1: Open the reference program ----
print("match_struct: Step 1 - Opening reference program...")

project = state.getProject()
pd = project.getProjectData()
root = pd.getRootFolder()

ref_file = None
for f in root.getFiles():
    if f.getName() == "lvgl_ref.o":
        ref_file = f
        break

if not ref_file:
    print("match_struct: ERROR - lvgl_ref.o not found in project")
    import sys
    sys.exit(1)

ref_prog = ref_file.getDomainObject(java.lang.Object(), True, True, monitor)
ref_fm = ref_prog.getFunctionManager()
ref_listing = ref_prog.getListing()

print("match_struct:   Reference has %d functions" % ref_fm.getFunctionCount())

# ---- Step 2: Compute fingerprints for reference functions ----
print("match_struct: Step 2 - Computing reference fingerprints...")

def get_mnemonic_sequence(prog, func):
    """Get normalized mnemonic sequence for a function."""
    mnemonics = []
    body = func.getBody()
    code_units = prog.getListing().getCodeUnits(body, True)
    for cu in code_units:
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn:
                mnemonics.append(mn.lower())
    return mnemonics

def get_basic_block_count(prog, func):
    """Count basic blocks in a function."""
    bbm = BasicBlockModel(prog)
    blocks = bbm.getCodeBlocksContaining(func.getBody(), monitor)
    count = 0
    while blocks.hasNext():
        blocks.next()
        count += 1
    return count

def get_call_count(prog, func):
    """Count outgoing calls from a function."""
    body = func.getBody()
    refs = prog.getReferenceManager()
    call_count = 0
    code_units = prog.getListing().getCodeUnits(body, True)
    for cu in code_units:
        if hasattr(cu, 'getMnemonicString'):
            mn = cu.getMnemonicString()
            if mn and mn.lower() in ('bl', 'blx'):
                call_count += 1
    return call_count

def compute_fingerprint(prog, func):
    """Compute a structural fingerprint for a function."""
    mnemonics = get_mnemonic_sequence(prog, func)
    size = func.getBody().getNumAddresses()
    bb_count = get_basic_block_count(prog, func)
    call_count = get_call_count(prog, func)

    # Mnemonic bigrams (pairs of consecutive mnemonics)
    bigrams = []
    for i in range(len(mnemonics) - 1):
        bigrams.append(mnemonics[i] + "+" + mnemonics[i+1])

    # Mnemonic histogram (normalized)
    hist = defaultdict(int)
    for m in mnemonics:
        hist[m] += 1

    # Hash of mnemonic sequence (exact match across compilers is rare,
    # but useful for deduplication)
    seq_hash = hashlib.md5(",".join(mnemonics).encode('utf-8')).hexdigest()

    # Bigram set (order-independent structural comparison)
    bigram_set = set(bigrams)

    return {
        'name': func.getName(),
        'size': size,
        'insn_count': len(mnemonics),
        'bb_count': bb_count,
        'call_count': call_count,
        'mnemonics': mnemonics,
        'seq_hash': seq_hash,
        'bigram_set': bigram_set,
        'hist': dict(hist),
    }

def similarity_score(fp1, fp2):
    """Compute similarity between two fingerprints (0.0 to 1.0)."""
    # Size ratio
    if fp1['size'] == 0 or fp2['size'] == 0:
        return 0.0
    size_ratio = min(fp1['size'], fp2['size']) / float(max(fp1['size'], fp2['size']))

    # Instruction count ratio
    if fp1['insn_count'] == 0 or fp2['insn_count'] == 0:
        return 0.0
    insn_ratio = min(fp1['insn_count'], fp2['insn_count']) / float(max(fp1['insn_count'], fp2['insn_count']))

    # Basic block count match
    bb_match = 1.0 if fp1['bb_count'] == fp2['bb_count'] else \
               0.8 if abs(fp1['bb_count'] - fp2['bb_count']) <= 1 else \
               0.5 if abs(fp1['bb_count'] - fp2['bb_count']) <= 2 else 0.2

    # Call count match
    call_match = 1.0 if fp1['call_count'] == fp2['call_count'] else \
                 0.7 if abs(fp1['call_count'] - fp2['call_count']) <= 1 else \
                 0.4 if abs(fp1['call_count'] - fp2['call_count']) <= 2 else 0.1

    # Bigram Jaccard similarity
    if len(fp1['bigram_set']) == 0 and len(fp2['bigram_set']) == 0:
        bigram_sim = 1.0
    elif len(fp1['bigram_set']) == 0 or len(fp2['bigram_set']) == 0:
        bigram_sim = 0.0
    else:
        intersection = len(fp1['bigram_set'] & fp2['bigram_set'])
        union = len(fp1['bigram_set'] | fp2['bigram_set'])
        bigram_sim = float(intersection) / union

    # Histogram cosine similarity
    all_keys = set(fp1['hist'].keys()) | set(fp2['hist'].keys())
    dot = sum(fp1['hist'].get(k, 0) * fp2['hist'].get(k, 0) for k in all_keys)
    mag1 = sum(v*v for v in fp1['hist'].values()) ** 0.5
    mag2 = sum(v*v for v in fp2['hist'].values()) ** 0.5
    hist_sim = dot / (mag1 * mag2) if mag1 > 0 and mag2 > 0 else 0.0

    # Weighted combination
    score = (size_ratio * 0.10 +
             insn_ratio * 0.10 +
             bb_match * 0.20 +
             call_match * 0.15 +
             bigram_sim * 0.25 +
             hist_sim * 0.20)

    return score

# Compute reference fingerprints (skip tiny functions < 4 instructions)
ref_fps = []
ref_count = 0
for func in ref_fm.getFunctions(True):
    name = func.getName()
    if name.startswith('_') and not name.startswith('_lv_'):
        continue
    fp = compute_fingerprint(ref_prog, func)
    if fp['insn_count'] < 4:
        continue
    ref_fps.append(fp)
    ref_count += 1

print("match_struct:   Computed %d reference fingerprints" % ref_count)

# ---- Step 3: Compute FW fingerprints for unnamed functions ----
print("match_struct: Step 3 - Computing FW fingerprints for unnamed functions...")

# Get all already-named lv_ functions (from match_lvgl.py or manual)
already_named = set()
for func in fm.getFunctions(True):
    n = func.getName()
    if n.startswith('lv_') or n.startswith('_lv_'):
        already_named.add(n)

# Build ref name set for collision checking
ref_names = set(fp['name'] for fp in ref_fps)

# Compute FW fingerprints for all FUN_ functions
fw_fps = []
fw_func_map = {}  # name -> func object
total_fw = 0
skipped = 0

for func in fm.getFunctions(True):
    name = func.getName()
    if not name.startswith('FUN_'):
        continue
    total_fw += 1

    # Quick size filter: skip functions that are way too small or too large
    # to match any LVGL function
    size = func.getBody().getNumAddresses()
    if size < 6:
        skipped += 1
        continue

    fp = compute_fingerprint(program, func)
    if fp['insn_count'] < 4:
        skipped += 1
        continue

    fw_fps.append(fp)
    fw_func_map[name] = func

print("match_struct:   Computed %d FW fingerprints (skipped %d tiny, from %d FUN_)" %
      (len(fw_fps), skipped, total_fw))

# ---- Step 4: Match by structural similarity ----
print("match_struct: Step 4 - Matching (this may take a while)...")

# For efficiency, pre-filter by size range (within 3x)
# Then compute similarity only for candidates

THRESHOLD_HIGH = 0.75
THRESHOLD_MEDIUM = 0.60

matches = []  # (fw_fp, ref_fp, score)
match_count = 0

# Index ref by size range for fast lookup
ref_by_size = defaultdict(list)
for rfp in ref_fps:
    bucket = rfp['insn_count'] // 5  # 5-instruction buckets
    ref_by_size[bucket].append(rfp)

for i, fw_fp in enumerate(fw_fps):
    if i % 500 == 0 and i > 0:
        print("match_struct:   ... processed %d/%d FW functions, %d matches so far" %
              (i, len(fw_fps), match_count))

    fw_bucket = fw_fp['insn_count'] // 5
    candidates = []
    for b in range(max(0, fw_bucket - 2), fw_bucket + 3):  # +/- 2 buckets = +/- 10 insns
        candidates.extend(ref_by_size.get(b, []))

    if not candidates:
        continue

    best_score = 0
    best_ref = None
    second_score = 0

    for rfp in candidates:
        # Skip already-matched ref names
        if rfp['name'] in already_named:
            continue

        score = similarity_score(fw_fp, rfp)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_ref = rfp
        elif score > second_score:
            second_score = score

    if best_ref and best_score >= THRESHOLD_MEDIUM:
        # Uniqueness: the best match should be significantly better than second best
        gap = best_score - second_score
        if gap >= 0.08 or best_score >= THRESHOLD_HIGH:
            confidence = 'HIGH' if best_score >= THRESHOLD_HIGH and gap >= 0.10 else 'MEDIUM'
            matches.append((fw_fp, best_ref, best_score, confidence, gap))
            match_count += 1

print("match_struct:   Found %d structural matches" % len(matches))

# ---- Step 5: Deduplicate (each ref name used at most once) ----
print("match_struct: Step 5 - Deduplicating...")

# Sort by score descending, then pick best for each ref name
matches.sort(key=lambda x: -x[2])
used_ref_names = set()
used_fw_names = set()
final_matches = []

for fw_fp, ref_fp, score, confidence, gap in matches:
    if ref_fp['name'] in used_ref_names:
        continue
    if ref_fp['name'] in already_named:
        continue
    if fw_fp['name'] in used_fw_names:
        continue
    used_ref_names.add(ref_fp['name'])
    used_fw_names.add(fw_fp['name'])
    final_matches.append((fw_fp, ref_fp, score, confidence, gap))

print("match_struct:   %d unique matches after dedup" % len(final_matches))

# ---- Step 6: Apply matches ----
print("match_struct: Step 6 - Applying matches...")

applied_high = 0
applied_medium = 0

for fw_fp, ref_fp, score, confidence, gap in final_matches:
    func = fw_func_map.get(fw_fp['name'])
    if not func:
        continue
    old_name = func.getName()

    if confidence == 'HIGH':
        func.setName(ref_fp['name'], SourceType.ANALYSIS)
        func.setComment("LVGL structural match: score=%.3f gap=%.3f [%s] (bb=%d/%d call=%d/%d insn=%d/%d)" %
                        (score, gap, confidence,
                         fw_fp['bb_count'], ref_fp['bb_count'],
                         fw_fp['call_count'], ref_fp['call_count'],
                         fw_fp['insn_count'], ref_fp['insn_count']))
        applied_high += 1
        print("match_struct:   HIGH  %.3f %s -> %s (bb=%d/%d call=%d/%d)" %
              (score, old_name, ref_fp['name'],
               fw_fp['bb_count'], ref_fp['bb_count'],
               fw_fp['call_count'], ref_fp['call_count']))
    else:
        # MEDIUM: add as plate comment for manual review
        listing.setComment(func.getEntryPoint(), CodeUnit.PLATE_COMMENT,
                          "LVGL structural candidate: %s score=%.3f gap=%.3f (bb=%d/%d call=%d/%d insn=%d/%d)" %
                          (ref_fp['name'], score, gap,
                           fw_fp['bb_count'], ref_fp['bb_count'],
                           fw_fp['call_count'], ref_fp['call_count'],
                           fw_fp['insn_count'], ref_fp['insn_count']))
        applied_medium += 1

print("match_struct: === DONE: %d HIGH (renamed), %d MEDIUM (commented) ===" %
      (applied_high, applied_medium))

# Clean up
ref_prog.release(java.lang.Object())
