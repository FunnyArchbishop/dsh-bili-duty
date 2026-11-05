#!/usr/bin/env node
/**
 * 偏好.mjs —— 把「你明确设过的规矩」+「你回过的判据标签」渲染成值班章程里的一段
 *
 * 为什么需要它（2026-11-05）：
 *   追问回来的标签只写进 `判据统计.json`，但**没有任何东西读它** ⇒ 你认真选了
 *   「选题妙 / 制作精良」，选片逻辑却完全不知道 ⇒ 表现成"我回了，但什么都没变" ✗
 *
 * 出口：`~/.dsh/bili-duty/duty.md` 里的 `<!-- PREFS:BEGIN -->…<!-- PREFS:END -->` 区块。
 *   duty.md 是**每轮都读**的用户可编辑章程 ⇒ 不用改插件、不用重启就能生效。
 *
 * 用法：
 *   node 偏好.mjs            渲染一次
 *   node 偏好.mjs --dry      只看会写成什么
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const HERE = path.dirname(fileURLToPath(import.meta.url))

const DUTY = process.env.BILI_DUTY_HOME
  || (() => { try { return JSON.parse(fs.readFileSync(new URL('./local.json', import.meta.url), 'utf8')).dutyHome } catch { return '' } })()
  || path.join(process.env.USERPROFILE || process.env.HOME || '', '.dsh', 'bili-duty')

const DRY = process.argv.includes('--dry')
const CFG = path.join(DUTY, 'config.json')
const PREFS = path.join(DUTY, 'prefs.json')
const TAGS = path.join(DUTY, '判据统计.json')
const CHARTER = path.join(DUTY, 'duty.md')
const MIRROR = process.argv.includes('--no-mirror') ? null : path.join(HERE, 'duty.md')

const BEGIN = '<!-- PREFS:BEGIN'
const END = '<!-- PREFS:END -->'

const readJson = (p, d) => { try { return JSON.parse(fs.readFileSync(p, 'utf8')) } catch { return d } }

function render() {
  const cfg = readJson(CFG, {}) || {}
  const prefs = readJson(PREFS, {}) || {}
  const tags = readJson(TAGS, {}) || {}
  const kws = (cfg.keywords || []).filter(Boolean)
  const words = (cfg.excludeWords || []).filter(Boolean)
  const ups = (prefs.banUps || []).filter(Boolean)

  const hard = []
  if (words.length) hard.push(`- **标题/UP 名里出现这些词的，整条跳过**：${words.join('、')}`)
  if (ups.length) hard.push(`- **这几个 UP 一律不推**：${ups.join('、')}`)
  if (Number(prefs.maxDurationMin) > 0) hard.push(`- **时长超过 ${prefs.maxDurationMin} 分钟的跳过**（合集/课程类豁免）`)
  if (Number(prefs.minPlay) > 0) hard.push(`- **播放量低于 ${prefs.minPlay} 的跳过**`)

  const sorted = Object.entries(tags).filter(([, v]) => Number(v) > 0).sort((a, b) => b[1] - a[1])
  const good = sorted.filter(([k]) => !/标题党|太水|太长|广告|听不懂/.test(k))
  const bad = sorted.filter(([k]) => /标题党|太水|太长|广告|听不懂/.test(k))

  const out = [BEGIN + ' 由 偏好.mjs 生成，别手改 -->', '# 他已经明说的偏好（2026-11-05 起自动生成）', '']
  out.push('## 硬过滤（宿主侧还会再拦一次，这里是让你少白读）')
  out.push(...(hard.length ? hard : ['- （没设）']))
  out.push('')
  out.push('## 他给 11 分时说的「好在哪」（次数越多越算数）')
  out.push(...(good.length ? good.map(([k, v]) => `- ${k} × ${v}`) : ['- （还没选过）']))
  out.push('')
  out.push('## 他给 -1 分时说的「差在哪」')
  out.push(...(bad.length ? bad.map(([k, v]) => `- ${k} × ${v}`) : ['- （还没选过）']))
  out.push('')
  out.push('## 现在的搜索关键词')
  out.push(kws.length ? kws.map((k) => '`' + k + '`').join(' · ') : '-（空）')
  out.push('')
  out.push('⚠️ 上面「好在哪」是他自己勾的判据，**挑片时按这个方向去衡量**，别只看播放量。')
  out.push(END)
  return out.join('\n')
}

function apply(file, block) {
  if (!fs.existsSync(file)) return false
  let txt = fs.readFileSync(file, 'utf8')
  for (;;) {
    const i = txt.indexOf(BEGIN)
    if (i < 0) break
    const j = txt.indexOf(END, i)
    txt = txt.slice(0, i) + (j < 0 ? '' : txt.slice(j + END.length))
  }
  fs.writeFileSync(file, txt.replace(/\s+$/, '') + '\n\n' + block + '\n', 'utf8')
  return true
}

const block = render()
if (DRY) {
  console.log(block)
} else {
  const a = apply(CHARTER, block)
  const b = MIRROR ? apply(MIRROR, block) : false
  const n = Object.values(readJson(TAGS, {}) || {}).reduce((s, v) => s + Number(v || 0), 0)
  console.log(`偏好块已写入：章程${a ? '✓' : '（缺）'} 镜像${b ? '✓' : '（缺）'}｜判据共 ${n} 次`)
}
