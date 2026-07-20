# 02 — RE toolchain (Ghidra DB)

The G2 fw 2.2.4.34 Ghidra database is maintained as a **reusable RE asset** so
that future homebrew / CFW work decompiles against a database that already reads
like real C. This note describes how it is built and kept reproducible.

- Ghidra project: `ghidra/ghidra_proj/` (program `g2_mainapp.bin`).
- **Load base = `0x39E680`** (file_offset 0 → runtime `0x39E680`). An earlier
  base of `0x438000` was wrong and made `autofunc` find 0 functions.
- The `.rep` database is a generated artifact and is **not committed** — rebuild
  it with [`ghidra/rebuild_db.sh`](../../ghidra/rebuild_db.sh).

## State reached

~2056 functions named (~24.6% of ~8349), ~499 `lv_*`, key structs typed, 244
protobuf structs applied. Decompilation reads like real C, e.g.
`APP_PbRxHealthFrameDataProcess(...) { HealthDataPackage *pHVar2 = ...; }`.

## The naming pipeline (`rebuild_db.sh`)

The big lever is that **the firmware embeds its own function names in log
strings**. Order of scripts:

1. **`autofunc.py`** — decompiles every `FUN_` function and reads the `__func__`
   argument of the logger `log_printf` (`0x43d514`, signature
   `(level, module_tag, file, __func__, line, fmt, ...)` — arg index 3 is the
   real function name) and of `FUN_0043ce46` (arg 2), renaming to it
   (`SourceType.ANALYSIS`). Names ~1479–1705 functions in about a minute.
   - **`__func__` deref fix:** the arg is a `char*` loaded from a literal pool;
     an early version decoded the pointer's own bytes as text and produced ~650
     garbled names. Fixed by making `is_ident` ASCII-only and having
     `resolve_str` try the direct string, then dereference one level
     (`rd32(sa)` → string). Never clobbers a hand (`USER_DEFINED`) name.
2. **`apply_knowledge.py`** — applies hand / workflow names (`USER_DEFINED`,
   override) from LVGL v9.3 + display/peer/power/burst function lists, plus
   inline framework names, globals, and the app-entry table.
3. **`apply_types.py`** — defines `lv_area_t`, `lv_image_dsc_t`, `app_cfg_t`,
   `peer_pkt_hdr_t`; applies `app_cfg_t` at the config globals.
4. **`apply_sigs.py`** — applies function signatures. Two sets:
   `sigs.json` (185, subsystem-focused) and `sigs2.json` (**1354,
   whole-firmware**). Typed-sig coverage went from ~3% → ~20% of all functions.
5. Protobuf: `apply_pb.py` → `apply_pb_types.py` → `apply_pb_decode.py`
   (see below).
6. Peer comms: `apply_peer.py` folds the inter-lens RE
   ([`docs/peer_comms_map.md`](../peer_comms_map.md)) into the DB.
7. IMU: `apply_imu_types.py` → `apply_imu_deep.py` → `apply_imu_reconfig.py`.
8. LVGL matching: `match_lvgl.py` → `match_lvgl_structural.py` →
   `match_lvgl_callgraph.py` (see below).
9. `apply_corrections.py`, then **`export_syms.py`** →
   [`patches/fw_2.2.4.34_syms.h`](../../patches/fw_2.2.4.34_syms.h)
   (`#define FW_<name> 0x..u` Thumb addresses, callable by name from CFW).

Reusable payload headers produced:
[`patches/fw_2.2.4.34_syms.h`](../../patches/fw_2.2.4.34_syms.h) (call firmware
by name) and
[`patches/fw_2.2.4.34_structs.h`](../../patches/fw_2.2.4.34_structs.h) (struct
layouts + RAM globals).

### Whole-firmware typing workflow

`extract_typing.py` decompiles every function and **groups by the source file
the firmware embeds in log strings** (`log_printf` arg 3 =
`...\pb_service_health.c`) → ~170 modules. A binning step packs them into ~69
~60 KB bins; one agent per bin returns per-function signatures
(`{addr,name,ret,params,confidence}`). Result: **1354 signatures** (809 high /
483 med / 62 low), 0 failures. The source-file grouping is itself a valuable
asset — it is the firmware's own module map (`pb_service_*`, `ui_*_page`,
`drv_bq27427` / `mx25u25643g` / `mspi_uled`, `sync_framework`, `app_ble_*`).

## Protobuf struct recovery

The firmware is **nanopb**; roughly half (service handlers + BLE decode) uses
nanopb message structs. **244 firmware-exact structs** are defined in the DB
(category `/pb`), each descriptor global labelled `<Name>_msgdesc`. Built
directly from the on-device `pb_msgdesc_t` descriptors (ground truth), not a
nanopb round-trip:

- `pb_reconstruct.py` decodes every descriptor → [`docs/pb_msgdesc.h`](../pb_msgdesc.h)
  (exact C structs) + a machine-exact per-field layout JSON.
- `apply_pb.py` creates the structs (real unions for oneofs, arrays for
  repeated, named fields at exact offsets) and labels the descriptor globals.
- `apply_pb_types.py` applies the structs to the service encoders by finding the
  tx-buffer alloc whose size matches the struct total (the RX handler decodes
  into the same per-service global, so it is typed too).
- `apply_pb_decode.py` types each sub-handler's payload param to its exact
  `/pb` struct.

**Key descriptor decode** (validated against real device traffic *and* firmware
code): per field `word0` low 2 bits = `atype` (width `1<<atype`); `tag =
word0>>2 & 0x3F`; `TB = word0>>8 & 0xFF` (`ltype=TB&0xF`, `htype=TB&0x30` =
req/opt/repeated/**oneof**, `ptrclass=TB&0xC0`); **`dataOffset` is an absolute
byte offset**; `data_size` = field byte width; a submessage's true `sizeof` ==
the `data_size` its parent records for that field (0 mismatches across all
parents = strong validation). Names came from the app side (Blutter — see
[06 — Terminal & protobuf](06-terminal-and-protobuf.md)) propagated transitively
through the submessage graph, shape-validated each hop → 156/244 named.

Validation example: the EvenAI encoder `@0x508942` allocates `0x20c` = 524 B
(== `EvenAIDataPackage` size) and writes `which_`@2 / union@4 exactly as
reconstructed; applying the struct made it decompile as
`pEVar1->commandId=2; ->which_EvenAIDataPackage=4; (->u).ctrl.status=...`.

## LVGL reference matching

The firmware is **stock LVGL v9.3** (IAR build; the `D:\...\lvgl_v9.3\...`
assert paths are intact), so RE reduces to mapping known LVGL API → firmware
address. Reference build: LVGL v9.3 from AmbiqMicro/lv_port_ambiq (`main-v9.3`)
compiled with `arm-none-eabi-gcc` for Cortex-M55 Thumb — 63/76 FW-referenced
source files compile → **978 reference symbols** in `lvgl_ref.o` (imported into
the Ghidra project alongside `g2_mainapp.bin`).

**487/978 reference symbols matched.** Final classification of the 978:

| Bucket | Count | Notes |
|--------|-------|-------|
| Matched | 487 (49.8%) | string(251) + callgraph(71) + BSim(97) + structural(8) + solo(81) |
| Inlined (≤40 B) | 223 (22.8%) | trivial getters/setters |
| Matched-customized | 7 | caller evidence confirms presence, IAR changed structure |
| Absent (Even unused) | 242 (24.7%) | widget APIs Even doesn't use |
| Unresolved collision | 16+5 | identical fingerprint, offset-only difference |

Methods tried (the cross-compiler IAR↔GCC gap is the core difficulty):

| Method | Renamed | Cross-compiler? |
|--------|---------|-----------------|
| String reference (`lv_*` unique xref) | 251 | N/A |
| Structural fingerprint (mnemonic bigram) | 8 | weak |
| Call-graph anchor (callee Jaccard + LCS) | 33 | strong |
| Iterative graph propagation | 38 | strong |
| BSim (decompiler p-code LSH) | 16 HIGH | strong |
| Multi-constraint verify | 48 | combined |
| **BinHunt symbolic (BB-level + Z3)** | **0** | **failed** |
| **Unicorn dynamic fingerprint** | 20 pure-unique | works (595 func/s) |

- **BinHunt failed** because GCC keeps `LV_ASSERT` as a call (a basic-block
  boundary) while IAR removes it, so BB counts/boundaries don't align. BB-level
  comparison assumes same-compiler; cross-compiler needs a function-level
  approach.
- **Symbolic execution** (angr + Z3) *can* prove equivalence: normalizing
  variable names (drop the auto-counter, keep the address) made `lv_obj_get_state`
  ref and fw expressions identical → equivalent proved. But angr is too slow for
  the full pipeline.
- **Unicorn dynamic fingerprinting** is the fastest: run ref and fw functions
  with identical concrete inputs and compare return values across N vectors. 20
  pure-unique matches; collisions come from assert-path convergence and are
  fixable by mocking valid LVGL object headers so the real logic runs.

To grow naming: add to the function lists or run a naming workflow over a
decompiled subsystem, then re-run `rebuild_db.sh`. `__func__` covers logging
functions; the ~6700 still-`FUN_` are mostly leaf helpers.
