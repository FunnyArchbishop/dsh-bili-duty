// 报告「不被砍」的行为回归测试 —— 直接拿**装好的 index.js 里那段真实代码**跑。
//
// 为什么不能只 node --check：我第一版补丁把 writeFileSync 那行吞掉了，
// 语法完全合法、check 通过，但函数变成"只读不写"✗ 只有行为测试抓得到。
import fs from 'node:fs'
import path from 'node:path'

const CANDIDATES = [
  path.join(process.env.USERPROFILE || process.env.HOME || '', '.dsh/profiles/web/node_modules/dsh-bili-scroll/index.js'),
]
const IDX = process.env.BILI_PLUGIN_INDEX || CANDIDATES.find((p) => fs.existsSync(p))
if (!IDX) {
  console.error('找不到 index.js（可以用 BILI_PLUGIN_INDEX 指过去）')
  process.exit(2)
}

const src = fs.readFileSync(IDX, 'utf8')

// ── 把 writeRoundNotesToReport 整段抠出来（花括号配平）──────────────────
const START = 'const writeRoundNotesToReport = () => {'
const s = src.indexOf(START)
if (s < 0) { console.error('index.js 里找不到 writeRoundNotesToReport'); process.exit(2) }
let i = s + START.length
let depth = 1
while (i < src.length && depth > 0) {
  const c = src[i]
  if (c === '{') depth++
  else if (c === '}') depth--
  i++
}
const body = src.slice(s, i)
if (!/writeFileSync/.test(body)) {
  console.error('✗ 这段代码里没有 writeFileSync —— 函数只读不写，补丁坏了')
  process.exit(1)
}

// ── 造假 fs，跑真代码 ───────────────────────────────────────────────────
function run(initial, notes) {
  // initial === undefined ⇒ 文件本来不存在（别塞个 undefined 进去，那样 existsSync 会说"存在"）
  const store = new Map(initial === undefined ? [] : [['OUT/day.md', initial]])
  const deps = {
    roundNotes: notes,
    cfg: { reportLevel: 'full' },
    outDir: 'OUT',
    dayKey: () => 'day',
    existsSync: (p) => store.has(p),
    readFileSync: (p) => store.get(p),
    writeFileSync: (p, v) => { store.set(p, v) },
    join: (...a) => a.join('/').replace(/\/+/g, '/'),
  }
  const fn = new Function(...Object.keys(deps), body + '\nreturn writeRoundNotesToReport()')
  fn(...Object.values(deps))
  return store.get('OUT/day.md')
}

let pass = 0, fail = 0
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  ok ? pass++ : fail++
  console.log((ok ? '✓ ' : '✗ ') + name + (ok ? '' : `\n    got  ${got}\n    want ${want}`))
}
const countBV = (t) => (t.match(/^###\s*BV/gm) || []).length
const countTD = (t) => (t.match(/^## 投递/gm) || []).length

// ── 用例 1：第 2 轮把条目追加在投递段之后（旧代码会全砍掉）──────────────
const case1 = [
  '### BV1aa', '第一条', '### BV1bb', '第二条', '### BV1cc', '第三条',
  '## 投递', '', '- 投递：只私信（第 1 轮）',
  '### BV1dd', '第四条', '### BV1ee', '第五条', '### BV1ff', '第六条',
].join('\n') + '\n'
const out1 = run(case1, ['投递：只私信（第 2 轮）'])
eq('第 2 轮之后，6 条条目一条不少', countBV(out1), 6)
eq('新投递记录写进去了', out1.includes('第 2 轮'), true)
eq('旧投递记录还在（没被静默删掉）', out1.includes('第 1 轮'), true)

// ── 用例 2：投递段就在文末（这种情况应该被替换，而不是越堆越多）──────────
const case2 = ['### BV1aa', '第一条', '## 投递', '', '- 投递：只私信（第 1 轮）'].join('\n') + '\n'
const out2 = run(case2, ['投递：只私信（第 2 轮）'])
eq('文末投递段被替换，条目没动', countBV(out2), 1)
eq('只剩一段投递（替换而不是追加）', countTD(out2), 1)
eq('内容是新一轮的', out2.includes('第 2 轮') && !out2.includes('第 1 轮'), true)

// ── 用例 3：报告还不存在（老行为：建文件 + 写头 + 投递）─────────────────
const out3 = run(undefined, ['投递：只私信（第 1 轮）'])
eq('文件不存在时会建一份带标题的', out3.split('\n')[0].startsWith('# 刷B站'), true)
eq('里面带投递记录', out3.includes('第 1 轮'), true)

// ── 用例 4：reportLevel=off 时什么都不做 ────────────────────────────────
{
  const store = new Map([['OUT/day.md', '### BV1aa\n第一条\n']])
  const deps = {
    roundNotes: ['x'], cfg: { reportLevel: 'off' }, outDir: 'OUT', dayKey: () => 'day',
    existsSync: (p) => store.has(p), readFileSync: (p) => store.get(p),
    writeFileSync: (p, v) => { store.set(p, v) }, join: (...a) => a.join('/').replace(/\/+/g, '/'),
  }
  const fn = new Function(...Object.keys(deps), body + '\nreturn writeRoundNotesToReport()')
  fn(...Object.values(deps))
  eq('reportLevel=off 不动文件', store.get('OUT/day.md'), '### BV1aa\n第一条\n')
}

console.log(`\n通过 ${pass} · 失败 ${fail}`)
if (fail) process.exitCode = 1
