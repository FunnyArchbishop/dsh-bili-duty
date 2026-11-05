// 软降权自测：在临时家目录里跑，不碰真实数据
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bili-demote-'))
process.env.BILI_SCORING_HOME = tmp          // ← 必须在 import 之前设，DUTY 是模块顶层算的
const m = await import('./评分.mjs')

let pass = 0, fail = 0
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  ok ? pass++ : fail++
  console.log((ok ? '✓ ' : '✗ ') + name + (ok ? '' : `\n    got ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`))
}
const DEMOTE = path.join(tmp, '降权.json')
const read = () => { try { return JSON.parse(fs.readFileSync(DEMOTE, 'utf8')) } catch { return null } }

// ── 第 1 次 -1：只降权，不删 ─────────────────────────────────────────────
const r1 = m.demote(['泰拉瑞亚'], 'BV1aaa', false)
eq('第 1 次进 soft 不进 hard', [r1.soft, r1.hard], [['泰拉瑞亚'], []])
eq('降权文件记了 n=1', read()['泰拉瑞亚'].n, 1)
eq('记下了是哪条视频', read()['泰拉瑞亚'].bvids, ['BV1aaa'])

// ── 第 2 次 -1：真删，并清掉降权记录 ────────────────────────────────────
const r2 = m.demote(['泰拉瑞亚'], 'BV1bbb', false)
eq('第 2 次升到 hard', [r2.soft, r2.hard], [[], ['泰拉瑞亚']])
eq('真删后清掉了降权记录', read()['泰拉瑞亚'], undefined)

// ── dry 不落盘 ───────────────────────────────────────────────────────────
const before = read()
const r3 = m.demote(['东方project'], 'BV1ccc', true)
eq('dry 也算出 soft', r3.soft, ['东方project'])
eq('dry 不写文件', read(), before)

// ── 两个词各自计数互不影响 ───────────────────────────────────────────────
m.demote(['甲词'], 'BV1d', false)
m.demote(['乙词'], 'BV1e', false)
eq('两个词各记 1 次', [read()['甲词'].n, read()['乙词'].n], [1, 1])

process.env.BILI_SCORING_HOME = ''
fs.rmSync(tmp, { recursive: true, force: true })
console.log(`\n通过 ${pass} · 失败 ${fail}`)
if (fail) process.exitCode = 1
