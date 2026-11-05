// 把 DSH 的 zstd 会话记录解出来，只打印「工具结果」的内容（截断），方便看某次调用到底返回了什么
// 用法：node 看工具结果.mjs <session.jsonl.zstd> [过滤子串] [最多几条]
import { readFileSync } from 'node:fs'
import zlib from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const file = process.argv[2]
const needle = process.argv[3] || ''
const max = Number(process.argv[4] || 8)

const buf = readFileSync(file)
const parts = []
let start = 0
for (let i = 0; i + 4 <= buf.length; i++) {
  if (buf[i] === 0x28 && buf[i + 1] === 0xb5 && buf[i + 2] === 0x2f && buf[i + 3] === 0xfd) {
    if (i > start) parts.push(buf.subarray(start, i).toString('utf8'))
    let nxt = buf.indexOf(MAGIC, i + 4)
    if (nxt === -1) nxt = buf.length
    try { parts.push(zlib.zstdDecompressSync(buf.subarray(i, nxt)).toString('utf8')) } catch { /* 半截帧 */ }
    start = nxt
    i = nxt - 1
  }
}
if (start < buf.length) parts.push(buf.subarray(start).toString('utf8'))

const found = []
for (const line of parts.join('\n').split('\n')) {
  if (!line.includes('"type":"tool/result"')) continue
  let o
  try { o = JSON.parse(line) } catch { continue }
  const txt = JSON.stringify(o?.data ?? o)
  if (needle && !txt.includes(needle)) continue
  found.push({ t: o.time, d: o?.data })
}
for (const f of found.slice(-max)) {
  const d = f.d ?? {}
  const name = d.name || d.callId || '?'
  let content = d.content ?? d.result ?? d.output ?? d
  const s = typeof content === 'string' ? content : JSON.stringify(content)
  console.log(`\n===== ${name} · ${new Date((f.t || 0) + 8 * 3600e3).toISOString().slice(11, 19)}`)
  console.log(s.slice(0, 700))
}
console.log(`\n(命中 ${found.length} 条工具结果)`)
