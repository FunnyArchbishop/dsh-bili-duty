// 把一轮里所有私信的原文按发送顺序解出来
import { readFileSync } from 'node:fs'
import zlib from 'node:zlib'

const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd])
const file = process.argv[2]
const buf = readFileSync(file)
const parts = []
let start = 0
for (let i = 0; i + 4 <= buf.length; i++) {
  if (buf[i] === 0x28 && buf[i + 1] === 0xb5 && buf[i + 2] === 0x2f && buf[i + 3] === 0xfd) {
    if (i > start) parts.push(buf.subarray(start, i).toString('utf8'))
    let nxt = buf.indexOf(MAGIC, i + 4)
    if (nxt === -1) nxt = buf.length
    try { parts.push(zlib.zstdDecompressSync(buf.subarray(i, nxt)).toString('utf8')) } catch { }
    start = nxt
    i = nxt - 1
  }
}
if (start < buf.length) parts.push(buf.subarray(start).toString('utf8'))

let n = 0
for (const line of parts.join('\n').split('\n')) {
  if (!line.includes('私信已投递')) continue
  if (!line.startsWith('{')) continue
  let o
  try { o = JSON.parse(line) } catch { continue }
  const txt = JSON.stringify(o)
  if (txt.includes('"type":"request/header"')) continue
  const raw = o?.data?.message?.content?.[0]?.content?.[0]?.text
  let inner = null
  try { inner = JSON.parse(raw)?.data?.msg_content } catch { }
  if (!inner) continue
  n++
  let body = inner
  try { body = JSON.parse(inner)?.content ?? inner } catch { }
  console.log(`\n================ 第 ${n} 条私信（${String(body).length} 字）================`)
  console.log(body)
}
console.log(`\n共 ${n} 条私信`)
