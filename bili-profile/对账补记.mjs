#!/usr/bin/env node
/**
 * 对账补记.mjs —— 把「判重表里记了『挑了』、但日报里漏写」的视频补回报告
 *
 * 为什么要它（2026-11-05 实测）：
 *   今天判重表记了 20 条「挑了」，日报 `out/2026-11-05.md` 里只有 6 个 `### BV` 行
 *   —— 12:04 那一轮挑的 12 条**整批没进报告**。后果：
 *     · 插件按报告里的 `###` 行数算「今天挑了几条」⇒ 以为只挑了 6 条（额度算多，会重复给）
 *     · `/last` 看到的是残缺的清单；`reports/` 里的单条笔记也少了那一批
 *   ⇒ 判重表是**流水账、最不容易出错**的那份，用它给报告补账。
 *
 * 同时核对真实标题：判重表里的 BV 也可能是错的（**BV 大小写敏感**，2026-11-05 真出过），
 * 对不上的条目补记时会挂一条 ⚠️ 说明，而不是悄悄把错链接写进报告。
 *
 * 用法：
 *   node 对账补记.mjs              补今天（默认）
 *   node 对账补记.mjs --days 3     连前 2 天一起补
 *   node 对账补记.mjs --dry        只看差多少，不写
 */
import { existsSync, readFileSync, writeFileSync, appendFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { homedir } from 'node:os'

const HERE = dirname(process.argv[1] || '.')
const LOCAL = (() => { try { return JSON.parse(readFileSync(join(HERE, 'local.json'), 'utf8')) } catch { return {} } })()
const DUTY = process.env.BILI_DUTY_HOME || LOCAL.dutyHome || join(homedir(), '.dsh', 'bili-duty')
const SEEN = join(DUTY, 'seen.md')
const OUT = join(DUTY, 'out')

const argv = process.argv.slice(2)
const has = (k) => argv.includes(k)
const pickArg = (k, d) => { const i = argv.indexOf(k); return i >= 0 ? Number(argv[i + 1]) || d : d }
const DAYS = Math.max(1, Math.min(30, pickArg('--days', 1)))
const DRY = has('--dry')

const bjNow = new Date(Date.now() + 8 * 3600e3)
const dayKey = (d) => d.toISOString().slice(0, 10)
const bjHHMM = () => new Date(Date.now() + 8 * 3600e3).toISOString().slice(11, 16)

// ── 判重表里「挑了」的那些 ────────────────────────────────────────────────
function seenPicked() {
  const map = new Map()          // date -> [{bvid,title,up}]
  if (!existsSync(SEEN)) return map
  for (const raw of readFileSync(SEEN, 'utf8').split('\n')) {
    const line = raw.trim()
    if (!line.startsWith('|')) continue
    const parts = line.split('|')
    if (parts.length < 6) continue
    const date = parts[1].trim()
    const bvid = parts[2].trim()
    const status = parts[parts.length - 2].trim()
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || !/^BV[0-9A-Za-z]{10}$/.test(bvid)) continue
    if (status !== '挑了') continue
    const up = parts[parts.length - 3].trim()
    const title = parts.slice(3, parts.length - 3).join('|').trim()
    if (!map.has(date)) map.set(date, [])
    const arr = map.get(date)
    if (!arr.some((x) => x.bvid === bvid)) arr.push({ bvid, title, up })
  }
  return map
}

// ── 报告里已经写了 `###` 的 ──────────────────────────────────────────────
function reportBVs(file) {
  if (!existsSync(file)) return new Set()
  return new Set([...readFileSync(file, 'utf8').matchAll(/^###\s*(BV[0-9A-Za-z]{10})/gm)].map((m) => m[1]))
}

// ── 核对真实标题 ─────────────────────────────────────────────────────────
const squash = (s) => String(s || '').toLowerCase().replace(/[^\p{L}\p{N}]/gu, '')
function lcs(a, b) {
  // ⚠️ 别加长度上限：以前写成 `k < 12`，长标题最多只能匹配 12 个字，
  //    再除以全长就全被判成"对不上"了（2026-11-05 误标了 3 条 ✗）
  let best = 0
  for (let i = 0; i < a.length; i++) {
    for (let j = 0; j < b.length; j++) {
      let k = 0
      while (i + k < a.length && j + k < b.length && a[i + k] === b[j + k]) k++
      if (k > best) best = k
    }
  }
  return best
}
async function realTitle(bvid) {
  try {
    const r = await fetch(`https://api.bilibili.com/x/web-interface/view?bvid=${bvid}`, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36',
        Referer: 'https://www.bilibili.com/',
      },
    })
    const j = await r.json()
    if (j?.code !== 0) return { reach: true, ok: false, real: `查不到（code=${j?.code}）` }
    return { reach: true, ok: true, real: String(j?.data?.title || '') }
  } catch {
    return { reach: false, ok: true, real: '' }
  }
}
async function verify(items) {
  const res = new Map()
  for (const x of items.slice(0, 25)) {
    const v = await realTitle(x.bvid)
    if (!v.reach || !v.real) { res.set(x.bvid, { ok: true }); continue }
    const a = squash(x.title)
    const b = squash(v.real)
    const ratio = a && b ? lcs(a, b) / Math.min(a.length, b.length) : 1
    res.set(x.bvid, { ok: v.ok && ratio >= 0.35, real: v.real })
  }
  return res
}

// ── 补记块 ───────────────────────────────────────────────────────────────
function blockFor(items, verified) {
  const head = [
    '',
    `## 补记（对账补记 · ${bjHHMM()} 自动补）`,
    '',
    '> 下面这些是当天**确实挑中了、判重表有记录，但报告里漏写**的 —— 宿主按 `###` 行数算额度，',
    '> 漏了就会把「今天挑了几条」算少。这里按判重表补回来，档位无从考证就如实标「补记」。',
    '',
  ]
  const body = items.flatMap((x) => {
    const v = verified.get(x.bvid)
    const out = [
      `### ${x.bvid}`,
      `${x.title || x.bvid}${x.up ? ' · ' + x.up : ''} · https://www.bilibili.com/video/${x.bvid}`,
    ]
    if (v && v.ok === false) {
      out.push(`> ⚠️ **这串 BV 可能打错了**：它实际指向《${String(v.real).slice(0, 40)}》，跟判重表里的标题对不上。`)
      out.push('> 链接按判重表原样保留（没自动改），要看请拿标题去 B站 搜。')
    }
    out.push('**档位**：可以看 —— （补记：当时没写进报告，只留了判重记录，没有判断依据）', '')
    return out
  })
  return head.concat(body).join('\n')
}

// ── 主流程 ───────────────────────────────────────────────────────────────
const picked = seenPicked()
const targets = []
for (let i = 0; i < DAYS; i++) targets.push(dayKey(new Date(bjNow.getTime() - i * 86400e3)))

const plan = []
let totalMissing = 0
for (const day of targets) {
  const want = picked.get(day) || []
  if (!want.length) continue
  const file = join(OUT, `${day}.md`)
  const have = reportBVs(file)
  const missing = want.filter((x) => !have.has(x.bvid))
  if (!missing.length) continue
  totalMissing += missing.length
  plan.push({ day, file, want: want.length, have: have.size, missing })
}

if (!totalMissing) {
  console.log('对账：报告和判重表一致，没有要补的。')
} else if (DRY) {
  console.log('对账（预览，没写）：')
  for (const p of plan) {
    console.log(`  ${p.day}: 判重表 ${p.want} 条 / 报告 ${p.have} 条 ⇒ 缺 ${p.missing.length} 条`)
    for (const m of p.missing) console.log(`     · ${m.bvid}  ${String(m.title).slice(0, 30)}`)
  }
} else {
  const verified = await verify(plan.flatMap((p) => p.missing))
  const flagged = [...verified.values()].filter((v) => v.ok === false).length
  for (const p of plan) {
    const block = blockFor(p.missing, verified)
    if (!existsSync(p.file)) {
      writeFileSync(p.file, `# 刷B站日报 ${p.day}\n`, 'utf8')
      appendFileSync(p.file, block, 'utf8')
      console.log(`  ${p.day}: 判重表 ${p.want} 条 / 报告 ${p.have} 条 ⇒ 补 ${p.missing.length} 条`)
      continue
    }
    // ⚠️ 必须插在**第一个 `## 投递` 之前**：宿主每轮收尾会用 indexOf('## 投递')
    //    把那个位置之后的全部内容砍掉（index.js L1480-1486）⇒ 追加到末尾等于送死 ✗
    const cur = readFileSync(p.file, 'utf8')
    const at = cur.indexOf('## 投递')
    if (at < 0) {
      appendFileSync(p.file, block, 'utf8')
    } else {
      const head = cur.slice(0, at).replace(/\s*$/, '') + '\n'
      const tail = cur.slice(at).replace(/^\s*/, '')
      writeFileSync(p.file, head + block.replace(/^\n+/, '') + '\n' + tail, 'utf8')
    }
    console.log(`  ${p.day}: 判重表 ${p.want} 条 / 报告 ${p.have} 条 ⇒ 补 ${p.missing.length} 条`)
  }
  console.log(`对账：共补 ${totalMissing} 条` + (flagged ? `，其中 ${flagged} 条 BV 标题对不上（已标 ⚠️）` : ''))
}
