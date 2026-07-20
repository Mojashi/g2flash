#!/bin/bash
# Reproduce the fully-named G2 fw 2.2.4.34 Ghidra DB from g2_mainapp.bin.
# Order matters. Run from this directory (g2flash/ghidra/).
# Pipeline: autofunc -> apply_knowledge -> apply_types -> apply_sigs -> apply_pb ->
#           apply_pb_types -> apply_pb_decode -> apply_peer -> apply_imu_types ->
#           apply_corrections -> export_syms
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
GH=/Users/mojashi/ghidra_11.3.1_PUBLIC/support/analyzeHeadless
PROJ="$HERE/ghidra_proj"
PROG=g2_mainapp.bin
PBPY=/Users/mojashi/.asdf/installs/python/3.13.2/bin/python3
cd "$HERE"

# 0) (Re)import if the program is missing. Base image at 0x438000.
if [ ! -d "$PROJ/g2fw.rep" ]; then
  echo "== fresh import + analyze (slow, ~5-10 min) =="
  "$GH" "$PROJ" g2fw -import "$HERE/$PROG" -loader BinaryLoader -loader-baseAddr 0x39E680 \
        -processor "ARM:LE:32:Cortex" -analysisTimeoutPerFile 3600 > /tmp/rebuild_import.log 2>&1
  echo "  import done."
fi

echo "== 1) autofunc: name from __func__ (825 + deref fix -> ~1705) =="
"$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript autofunc.py > /tmp/rebuild_1.log 2>&1
grep autofunc: /tmp/rebuild_1.log || true

echo "== 2) apply_knowledge: hand + LVGL + FW names + app_entry_t =="
if [ -f "$HERE/apply_knowledge.py" ]; then
  "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_knowledge.py > /tmp/rebuild_2.log 2>&1
  grep -E "applied|renamed" /tmp/rebuild_2.log || true
else echo "  (no apply_knowledge.py, skipping)"; fi

echo "== 3) apply_types: struct definitions =="
[ -f "$HERE/apply_types.py" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_types.py > /tmp/rebuild_3.log 2>&1 && grep -E "types:" /tmp/rebuild_3.log || echo "  (skipped)"

echo "== 3b) apply_sigs: function signatures (sigs.json + sigs2.json) =="
for SF in sigs.json sigs2.json; do
  [ -f "$HERE/apply_sigs.py" ] && [ -f "$HERE/$SF" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_sigs.py "$HERE/$SF" > "/tmp/rebuild_3b_$SF.log" 2>&1 && grep -E "apply_sigs:" "/tmp/rebuild_3b_$SF.log" || echo "  (no $SF)"
done

echo "== 3c) apply_pb: firmware-exact protobuf message structs =="
[ -x "$PBPY" ] && [ -f "$HERE/pb_reconstruct.py" ] && "$PBPY" "$HERE/pb_reconstruct.py" > /tmp/rebuild_3c_gen.log 2>&1 && grep -E "wrote|named descriptors" /tmp/rebuild_3c_gen.log || echo "  (pb_reconstruct skipped)"
[ -f "$HERE/apply_pb.py" ] && [ -f "$HERE/pb_layout.json" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_pb.py "$HERE/pb_layout.json" > /tmp/rebuild_3c.log 2>&1 && grep -E "apply_pb:" /tmp/rebuild_3c.log || echo "  (no pb_layout.json)"
[ -f "$HERE/apply_pb_types.py" ] && [ -f "$HERE/pb_layout.json" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_pb_types.py "$HERE/pb_layout.json" > /tmp/rebuild_3d.log 2>&1 && grep -E "apply_pb_types:" /tmp/rebuild_3d.log || true

echo "== 3e) apply_pb_decode: pb handler payload param types =="
[ -f "$HERE/apply_pb_decode.py" ] && [ -f "$HERE/pb_decode_map.json" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_pb_decode.py "$HERE/pb_decode_map.json" > /tmp/rebuild_3e.log 2>&1 && grep -E "apply_pb_decode:" /tmp/rebuild_3e.log || true

echo "== 3f) apply_peer: inter-lens peer-comms structs + signatures =="
[ -f "$HERE/apply_peer.py" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_peer.py > /tmp/rebuild_3f.log 2>&1 && grep -E "apply_peer:" /tmp/rebuild_3f.log || true

echo "== 3g) apply_imu_types: IMU sensor ring buffer types + function names =="
[ -f "$HERE/apply_imu_types.py" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_imu_types.py > /tmp/rebuild_3g.log 2>&1 && grep -E "apply_imu" /tmp/rebuild_3g.log || true

echo "== 3i) apply_imu_deep: BHI260AP chip driver + FIFO parsers + auto-brightness interference =="
[ -f "$HERE/apply_imu_deep.py" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_imu_deep.py > /tmp/rebuild_3i.log 2>&1 && grep -E "apply_imu_deep:" /tmp/rebuild_3i.log || true

echo "== 3j) apply_imu_reconfig: sensor parameter setup + channel disable/config + interrupts =="
[ -f "$HERE/apply_imu_reconfig.py" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_imu_reconfig.py > /tmp/rebuild_3j.log 2>&1 && grep -E "apply_imu_reconfig:" /tmp/rebuild_3j.log || true

echo "== 3k) match_lvgl: LVGL symbol matching from reference build =="
[ -f "$HERE/match_lvgl.py" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript match_lvgl.py > /tmp/rebuild_3k.log 2>&1 && grep -E "match_lvgl:" /tmp/rebuild_3k.log || true

echo "== 3l) match_lvgl_structural: LVGL structural binary matching =="
[ -f "$HERE/match_lvgl_structural.py" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript match_lvgl_structural.py > /tmp/rebuild_3l.log 2>&1 && grep -E "match_struct:" /tmp/rebuild_3l.log || true

echo "== 3m) match_lvgl_callgraph: LVGL call-graph matching =="
[ -f "$HERE/match_lvgl_callgraph.py" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript match_lvgl_callgraph.py > /tmp/rebuild_3m.log 2>&1 && grep -E "match_cg:" /tmp/rebuild_3m.log || true

echo "== 3h) apply_corrections: corrected RE claims =="
[ -f "$HERE/apply_corrections.py" ] && "$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript apply_corrections.py > /tmp/rebuild_3h.log 2>&1 && grep -E "apply_corrections:" /tmp/rebuild_3h.log || true

echo "== 4) export payload header =="
"$GH" "$PROJ" g2fw -process "$PROG" -noanalysis -scriptPath "$HERE" -postScript export_syms.py ./fw_2.2.4.34_syms.h > /tmp/rebuild_4.log 2>&1
grep exported /tmp/rebuild_4.log || true
cp -f ./fw_2.2.4.34_syms.h /Users/mojashi/repos/odd/g2flash/patches/ 2>/dev/null || true
echo "== done. DB in $PROJ, header in patches/ =="
