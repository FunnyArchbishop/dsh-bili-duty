// 一次性体检：把这轮会话里「私信原文」「图片块数量」「请求里到底带没带图」都挖出来
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
const lines = parts.join('\n').split('\n').filter((l) => l.startsWith('{'))

// 1) 私信原文
for (const l of lines) {
  if (!l.includes('私信已投递')) continue
  try {
    const o = JSON.parse(l)
    const t = JSON.stringify(o)
    const m = t.match(/msg_content\\":\s*\\"((?:[^"\\]|\\.)*)/)
    const raw = o?.data?.message?.content?.[0]?.content?.[0]?.text
    let inner = null
    try { inner = JSON.parse(raw)?.data?.msg_content } catch { }
    console.log('\n========== 私信原文 ==========')
    console.log(inner ?? raw ?? t.slice(0, 1200))
  } catch (e) { console.log('私信解析失败', e.message) }
}

// 2) 工具结果里的 image 块
let imgBlocks = 0
const placeholders = new Set()
for (const l of lines) {
  if (!l.includes('"type":"tool/result"')) continue
  const n = (l.match(/"type":"image"/g) || []).length
  imgBlocks += n
  for (const m of l.matchAll(/"(?:text|reason|note)"\s*:\s*"([^"]{0,120}(?:offload|unavailable|handle|跳过)[^"]{0,120})"/gi)) placeholders.add(m[1])
}
console.log('\n========== 工具结果里的 image 块数：' + imgBlocks + ' ==========')
if (placeholders.size) console.log('可疑占位文本：', [...placeholders].slice(0, 6))

// 3) 发给模型的请求里带图了吗 —— 数每条 user/tool 消息里的 image
let reqImgs = 0
for (const l of lines) {
  if (!l.includes('"type":"request/header"')) continue
  if (l.includes('"type":"image"')) reqImgs++
}
console.log('request/header 里含 image 的条数：', reqImgs)

// 4) 模型自己说的「看不见」原话
for (const l of lines) {
  if (!/看不见|image unavailable|不支持图片/.test(l)) continue
  const m = l.match(/(?:看不见|image unavailable|不支持图片)[^"\\]{0,80}/)
  if (m) { console.log('\n模型原话片段：', m[0].slice(0, 200)); break }
}
