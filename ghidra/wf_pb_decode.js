export const meta = {
  name: 'pb-decode-map',
  description: 'Map each pb encode/decode handler param to its firmware-exact /pb message struct',
  phases: [{ title: 'Map', detail: 'one agent per pb-service module, in parallel' }],
}

const A = typeof args === 'string' ? JSON.parse(args) : args
const MODULES = A.modules
const STRUCTS = A.structNamesPath

const COMMON =
  `Reverse-engineering task on Even Realities G2 firmware 2.2.4.34. Each protobuf service has handler functions ` +
  `that ENCODE an app message struct to bytes or DECODE received bytes into a message struct. For EACH function ` +
  `listed, identify the ONE parameter that carries the protobuf MESSAGE STRUCT — for an encoder that is the ` +
  `INPUT payload being serialized (often named pData/msg/item/info); for a decoder it is the DESTINATION struct ` +
  `being filled. Then give the exact firmware struct name it points to, chosen from the /pb struct name list ` +
  `(read STRUCT_NAMES file). The function name usually contains the message name; resolve abbreviations against ` +
  `the list (e.g. "EvenAICtrl" -> "EvenAIControl", "...Info"/"...Msg" kept as-is, "...MultData" -> exact). ` +
  `Use the decompiled BODY (read BODY file; functions are marked "// ===== name @ 0xADDR =====") to confirm ` +
  `which param is the struct vs a raw byte buffer / length / stream. ` +
  `RULES: (1) Return a mapping ONLY when you are confident the struct name is an EXACT entry in the /pb list. ` +
  `(2) SKIP top-level "...FrameDataProcess"/"...RxData" functions whose payload param is a raw byte frame (u8*), ` +
  `not a message struct — omit them. (3) SKIP any function with no confident struct match. (4) "param" MUST be ` +
  `the exact parameter NAME from the provided signature. Your output IS the data.`

const SCHEMA = {
  type: 'object',
  properties: {
    mappings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          addr: { type: 'string' },
          param: { type: 'string', description: 'exact param name from the given signature' },
          struct: { type: 'string', description: 'exact /pb struct name' },
          confidence: { type: 'string', enum: ['high', 'med', 'low'] },
        },
        required: ['addr', 'param', 'struct'],
      },
    },
  },
  required: ['mappings'],
}

function sigText(f) {
  const ps = f.params.map((p) => `${p.type} ${p.name}`).join(', ')
  return `  ${f.name} @${f.addr}(${ps})`
}

const results = await parallel(MODULES.map((m) => () =>
  agent(
    `${COMMON}\n\nMODULE: ${m.module}\nSTRUCT_NAMES file: ${STRUCTS}\nBODY file: ${m.bodyPath}\n\n` +
    `FUNCTIONS (name @addr(params)):\n${m.funcs.map(sigText).join('\n')}`,
    { label: `map:${m.module}`, phase: 'Map', schema: SCHEMA }
  )
))

const all = []
for (const r of results) if (r && r.mappings) all.push(...r.mappings)
log(`mapped ${all.length} pb handler params across ${results.filter(Boolean).length}/${MODULES.length} modules`)
return { mappings: all }
