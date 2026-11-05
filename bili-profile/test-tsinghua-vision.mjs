// 探针：确认「清华给出的 DeepSeek 接口」(llmapi.paratera.com) 是否吃图 + 吃 reasoning_effort
// 用法：node test-tsinghua-vision.mjs [图片路径]
import { readFileSync } from 'node:fs'

const KEY = process.env.TSINGHUA_API_API_KEY || ''
if (!KEY) {
  console.error('缺环境变量 TSINGHUA_API_API_KEY（这个探针不内置任何 key）')
  process.exit(1)
}
const BASE = 'https://llmapi.paratera.com/v1'
const MODEL = 'DeepSeek-V4-Flash-Vision-Exp'
const imgPath = process.argv[2]
if (!imgPath) { console.error('用法：node test-tsinghua-vision.mjs <图片路径>'); process.exit(1) }

const b64 = readFileSync(imgPath).toString('base64')
const dataUrl = 'data:image/png;base64,' + b64

async function call(extra = {}, label = '') {
  const body = {
    model: MODEL,
    messages: [
      {
        role: 'user',
        content: [
          { type: 'text', text: '这张图里画的是什么？只回答一句话，说清是什么类型的东西。' },
          { type: 'image_url', image_url: { url: dataUrl } },
        ],
      },
    ],
    max_tokens: 300,
    ...extra,
  }
  const t0 = Date.now()
  const res = await fetch(BASE + '/chat/completions', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + KEY, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const text = await res.text()
  let json = null
  try { json = JSON.parse(text) } catch { /* 非 JSON，原样看 */ }
  const ms = Date.now() - t0
  console.log(`\n===== ${label} [${extra.reasoning_effort ? 'reasoning_effort=' + extra.reasoning_effort : '无 effort'}] HTTP ${res.status} ${ms}ms`)
  if (!json) { console.log('RAW:', text.slice(0, 800)); return }
  if (json.error) { console.log('ERROR:', JSON.stringify(json.error)); return }
  const ch = json.choices?.[0]
  console.log('finish_reason:', ch?.finish_reason)
  console.log('content:', JSON.stringify(ch?.message?.content))
  const rc = ch?.message?.reasoning_content
  if (rc) console.log('reasoning_content(前120字):', JSON.stringify(String(rc).slice(0, 120)))
  console.log('usage:', JSON.stringify(json.usage))
}

await call({}, '图片识别')
await call({ reasoning_effort: 'high' }, '图片识别+effort')
