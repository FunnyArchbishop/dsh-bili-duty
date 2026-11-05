// 端到端演练：在**临时沙箱目录**里跑一遍「纯文字评价 → 缓冲区 → 学习 → 改关键词 + 重写画像」
// 真实数据一行都不动（BILI_SCORING_HOME 指向临时目录）。
import { spawnSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const LOCAL = (() => { try { return JSON.parse(fs.readFileSync(new URL('./local.json', import.meta.url), 'utf8')) } catch { return {} } })()
const REAL = process.env.BILI_DUTY_HOME || LOCAL.dutyHome || (process.env.USERPROFILE || process.env.HOME || '') + '/.dsh/bili-duty'
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bili-score-'))
console.log('沙箱目录：', tmp)

// 拷一份配置和画像进去
fs.copyFileSync(path.join(REAL, 'config.json'), path.join(tmp, 'config.json'))
const persona = fs.readFileSync(path.join(REAL, 'persona.md'), 'utf8')
  .split('<!-- RATINGS:BEGIN')[0]                 // 去掉旧块，练一次从零生成
fs.writeFileSync(path.join(tmp, 'persona.md'), persona, 'utf8')

// 造 4 条纯文字评价：其中 2 条都在夸「泰拉瑞亚的电路」，1 条在抱怨「高数」
const R = (bvid, title, note, extra = {}) => JSON.stringify({
  at: `2026-11-05T0${Math.floor(Math.random() * 9) + 1}:00:00.000Z`,
  date: '2026-11-05', bvid, title, score: null, note, src: 'dm', learned: false,
  polarity: 'unknown', ...extra,
})
const rows = [
  R('BV1aaa', '泰拉瑞亚里的32位RISC-V CPU', '泰拉瑞亚的电路这段太强了，五级流水讲得清楚'),
  R('BV1bbb', '泰拉瑞亚速通世界纪录解说', '泰拉瑞亚的电路部分好看，其他一般'),
  R('BV1ccc', '高等数学教学视频 3.0版', '又是高数网课，太无聊了'),
  R('BV1ddd', '某个绘画过程', '这条就随便看看'),
]
fs.writeFileSync(path.join(tmp, 'ratings.jsonl'), rows.join('\n') + '\n', 'utf8')

const run = (args) => {
  const r = spawnSync(process.execPath, [path.join(here, '评分.mjs'), ...args], {
    env: { ...process.env, BILI_SCORING_HOME: tmp, BILI_SCORING_MIRROR: path.join(tmp, 'persona-mirror.md') },
    encoding: 'utf8',
  })
  return (r.stdout || '') + (r.stderr || '')
}

console.log('\n───── node 评分.mjs --learn ─────')
console.log(run(['--learn']).trim())

const cfg = JSON.parse(fs.readFileSync(path.join(tmp, 'config.json'), 'utf8'))
const before = JSON.parse(fs.readFileSync(path.join(REAL, 'config.json'), 'utf8'))
console.log('\n───── 结果 ─────')
console.log('沙箱 keywords :', cfg.keywords)
console.log('真实 keywords :', before.keywords, '（应当完全没变）')
const led = fs.readFileSync(path.join(tmp, 'ratings.jsonl'), 'utf8').trim().split('\n').map(JSON.parse)
console.log('缓冲区已标记学完：', led.filter((r) => r.learned).length, '/', led.length)

const p = fs.readFileSync(path.join(tmp, 'persona.md'), 'utf8')
const i = p.indexOf('## 他随口说的')
console.log('\n───── 画像里新增的两段 ─────')
console.log(p.slice(i, p.indexOf('RATINGS:END')).trim())

const cleanup = process.argv.includes('--keep') ? () => { } : () => fs.rmSync(tmp, { recursive: true, force: true })
cleanup()
