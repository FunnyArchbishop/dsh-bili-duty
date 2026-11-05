// 把 DSH 的 zstd 会话记录解出来，搜关键字（多帧 zstd，逐帧解）
import { readFileSync } from 'node:fs'
import zlib from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const file = process.argv[2]
const needle = process.argv[3] || ''
const buf = readFileSync(file)

const out = []
let start = 0
for (let i = 0; i + 4 <= buf.length; i++) {
  if (buf[i] === 0x28 && buf[i + 1] === 0xb5 && buf[i + 2] === 0x2f && buf[i + 3] === 0xfd) {
    if (i > start) out.push(buf.subarray(start, i).toString('utf8'))
    const end = (() => {
      const nxt = buf.indexOf(MAGIC, i + 4)
      return nxt === -1 ? buf.length : nxt
    })()
    try {
      out.push(zlib.zstdDecompressSync(buf.subarray(i, end)).toString('utf8'))
    } catch {
      out.push(buf.subarray(i, end).toString('utf8'))
    }
    start = end
    i = end - 1
  }
}
if (start < buf.length) out.push(buf.subarray(start).toString('utf8'))
const text = out.join('\n')

// 抽所有出现过的 provider / model 线索
const hits = new Map()
const add = (k) => hits.set(k, (hits.get(k) || 0) + 1)
for (const m of text.matchAll(/"(?:provider|providerId|model|modelId)"\s*:\s*"([^"]{2,60})"/g)) add(m[1])
console.log('--- provider/model 字段出现次数 ---')
for (const [k, v] of [...hits.entries()].sort((a, b) => b[1] - a[1]).slice(0, 20)) console.log(String(v).padStart(5), k)

if (needle) {
  console.log(`\n--- 含 "${needle}" 的行（最多 12 行）---`)
  const lines = text.split('\n').filter((l) => l.toLowerCase().includes(needle.toLowerCase()))
  for (const l of lines.slice(0, 12)) console.log(l.slice(0, 400))
  console.log(`(共 ${lines.length} 行命中)`)
}
console.log('\n解出字符数:', text.length)
