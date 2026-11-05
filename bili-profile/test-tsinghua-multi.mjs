// 探针：清华网关（llmapi.paratera.com）一次多图到底认不认
// 用法：node test-tsinghua-multi.mjs <图1> <图2> [图3...]
import { readFileSync } from 'node:fs'

const KEY = process.env.TSINGHUA_API_API_KEY || ''
if (!KEY) {
  console.error('缺环境变量 TSINGHUA_API_API_KEY（这个探针不内置任何 key）')
  process.exit(1)
}
const BASE = 'https://llmapi.paratera.com/v1'
const MODEL = 'DeepSeek-V4-Flash-Vision-Exp'
const paths = process.argv.slice(2)

const imgs = paths.map((p) => ({
  type: 'image_url',
  image_url: { url: 'data:image/png;base64,' + readFileSync(p).toString('base64') },
}))

const body = {
  model: MODEL,
  messages: [
    {
      role: 'user',
      content: [
        { type: 'text', text: `一共 ${imgs.length} 张图。请按顺序逐张一句话说明每张图里是什么，用 1 2 3 编号，每张都要说。` },
        ...imgs,
      ],
    },
  ],
  max_tokens: 1600,
}

const res = await fetch(BASE + '/chat/completions', {
  method: 'POST',
  headers: { Authorization: 'Bearer ' + KEY, 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})
const j = await res.json()
console.log('HTTP', res.status)
if (j.error) console.log('ERROR', JSON.stringify(j.error))
else {
  console.log('imgs sent:', imgs.length)
  console.log('finish:', j.choices?.[0]?.finish_reason)
  console.log('content:', j.choices?.[0]?.message?.content)
  console.log('usage:', JSON.stringify(j.usage))
}
