// 评分.mjs 的行为自测（不碰真实数据：关键词只做 dry 预览）
import { parseMessage, extractGoodKeywords, extractBadKeywords, applyKeywordPatch, polarityOf, repeatedPhrases, titlePhrases } from './评分.mjs'

let pass = 0, fail = 0
const eq = (name, got, want) => {
  const ok = JSON.stringify(got) === JSON.stringify(want)
  ok ? pass++ : fail++
  console.log(`${ok ? '✓' : '✗'} ${name}`)
  if (!ok) console.log(`    got  ${JSON.stringify(got)}\n    want ${JSON.stringify(want)}`)
}

// ── 1. 解析 ──────────────────────────────────────────────────────────────
eq('纯数字对', parseMessage('1=10 3=9'),
  [{ n: 1, score: 10, reason: '' }, { n: 3, score: 9, reason: '' }])

eq('11 分 + 理由', parseMessage('2=11 空岛那个取舍讲得太清楚了'),
  [{ n: 2, score: 11, reason: '空岛那个取舍讲得太清楚了' }])

eq('-1 分 + 理由', parseMessage('5=-1 标题党，全程废话'),
  [{ n: 5, score: -1, reason: '标题党，全程废话' }])

eq('混合：只评一部分', parseMessage('1=10 4=11 泰拉电路那段绝了 7=0'),
  [{ n: 1, score: 10, reason: '' },
   { n: 4, score: 11, reason: '泰拉电路那段绝了' },
   { n: 7, score: 0, reason: '' }])

eq('纯文字评价（不打分）', parseMessage('4 调色板真舒服'),
  [{ n: 4, score: null, reason: '调色板真舒服' }])

eq('中文冒号也行', parseMessage('3：−1'.replace('−1', '-1')),
  [{ n: 3, score: -1, reason: '' }])

eq('我们自己的清单不该被当成评价', parseMessage('今天挑了 12 条，分两批发。'), [])

eq('越界分数被钳住', parseMessage('2=99'), [{ n: 2, score: 11, reason: '' }])

// ── 2. 提词 ──────────────────────────────────────────────────────────────
const kw = ['东方project', '泰拉瑞亚', '绘画过程', '原神']
eq('11 分提词：夸的点在标题里', extractGoodKeywords('空岛那个取舍讲得太清楚了', '仅一格方块的空岛生存？！', '', kw),
  ['空岛生存'])
eq('11 分提词：理由和标题没交集 ⇒ 不乱加', extractGoodKeywords('讲得很清楚', '仅一格方块的空岛生存？！', '', kw), [])
eq('-1 分删词：理由里点名的词', extractBadKeywords('高数上课太无聊了', ['东方project', '高数', '泰拉瑞亚']), ['高数'])
eq('-1 分删词：理由没点名 ⇒ 不删', extractBadKeywords('标题党，全是废话', kw), [])

// ── 3. 纯文字评价：缓冲区学习 ────────────────────────────────────────────
eq('极性：夸', polarityOf('泰拉那个电路讲得太强了'), 'positive')
eq('极性：骂', polarityOf('标题党，全程废话'), 'negative')
eq('极性：看不出来', polarityOf('关于这个视频'), 'unknown')
eq('一条评价里的标题短语', titlePhrases('空岛那段取舍讲得太清楚了', '仅一格方块的空岛生存？！'), ['空岛'])

const rep = repeatedPhrases(['泰拉瑞亚的电路太强', '泰拉瑞亚的电路讲得清楚', '一个无关的绘画过程'])
eq('反复出现的词被抓到（且不切成残词）', rep.join('|'), '泰拉瑞亚的电路')
eq('不会出现「泰拉瑞亚的电」这种错位残词', rep.some((w) => w === '泰拉瑞亚的电' || w === '拉瑞亚的电路'), false)
eq('只出现一次的词不算数', rep.some((w) => w.includes('绘画过程')), false)
eq('只出现一次 = 缓冲区不动作', repeatedPhrases(['单说有氧运动真好', '完全不同的另一句', '第三句也无关']).length, 0)

// ── 4. 关键词落盘只做预览 ────────────────────────────────────────────────
import fs from 'node:fs'
const LOCAL = (() => { try { return JSON.parse(fs.readFileSync(new URL('./local.json', import.meta.url), 'utf8')) } catch { return {} } })()
const CFG = process.env.BILI_DUTY_HOME ? process.env.BILI_DUTY_HOME + '/config.json'
  : (LOCAL.dutyHome || (process.env.USERPROFILE || process.env.HOME || '') + '/.dsh/bili-duty') + '/config.json'
const cur = (JSON.parse(fs.readFileSync(CFG, 'utf8')).keywords || [])
const victim = cur[cur.length - 1]
const r1 = applyKeywordPatch({ add: ['测试用的新词'], remove: victim ? [victim] : [], dry: true })
eq('dry 预览能算出增删', { added: r1.added, removed: r1.removed }, { added: ['测试用的新词'], removed: victim ? [victim] : [] })
eq('dry 预览不改文件（keywords 还是原样）',
  JSON.stringify((JSON.parse(fs.readFileSync(CFG, 'utf8')).keywords || [])), JSON.stringify(cur))

console.log(`\n通过 ${pass} · 失败 ${fail}`)
if (fail) process.exitCode = 1
