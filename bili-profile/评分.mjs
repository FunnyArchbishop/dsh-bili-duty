#!/usr/bin/env node
/**
 * 评分.mjs —— 「刷B站」的评价闭环（取代旧的 打分.mjs）
 *
 * 使用者在大号私信里怎么说，这里就怎么收：
 *
 *   1=10 3=9                  ← 普通打分（0~10）
 *   2=11 空岛那个取舍讲得太清楚了   ← **特别好**：11 分 + 说出好在哪 ⇒ 从这句话里提词，加进 keywords
 *   5=-1 标题党，全程废话         ← **特别差**：-1 分 + 说出差在哪 ⇒ 把相关词从 keywords 里删掉
 *   4 调色板真舒服               ← 只写一句评价、不打分也行
 *   （不想看给 0；**不用每条都评**，跳过就是没意见）
 *
 * 用法：
 *   node 评分.mjs              收取私信里的新评价（记账 + 改关键词 + 重算画像）
 *   node 评分.mjs --dry        只解析、只预览，什么都不写
 *   node 评分.mjs --list       看台账
 *   node 评分.mjs --report     只重算 persona.md 里的 RATINGS 块
 *   node 评分.mjs --set 3 10   手动记一条（3 号条目 10 分）
 */
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

// ── 路径 ──────────────────────────────────────────────────────────────────
// ── 本地配置（local.json 不进仓库；环境变量优先）──────────────────────────
const HERE_DIR = path.dirname(path.resolve(process.argv[1] || '.'))
const LOCAL_CFG = (() => { try { return JSON.parse(fs.readFileSync(path.join(HERE_DIR, 'local.json'), 'utf8')) } catch { return {} } })()
const HOME_DIR = process.env.USERPROFILE || process.env.HOME || ''
const DUTY = process.env.BILI_SCORING_HOME || LOCAL_CFG.dutyHome || path.join(HOME_DIR, '.dsh', 'bili-duty')
const OWNER = Number(process.env.BILI_OWNER_UID || LOCAL_CFG.ownerUid || 0)   // 你的 B站 大号 uid（local.json）
const LEDGER = path.join(DUTY, 'ratings.jsonl')
const STATE = path.join(DUTY, 'scoring-state.json')
const KLOG = path.join(DUTY, 'keyword-log.jsonl')

// ── 读私信用的 dm.mjs 来自插件 dsh-bili-scroll ───────────────────────────
// 默认按 `~/.dsh/profiles/web/node_modules/dsh-bili-scroll/lib/dm.mjs` 找；
// 装到别处就用环境变量 BILI_DM_LIB 指过去（形如 file:///.../lib/dm.mjs）。
let loadCred = () => null
let fetchMsgs = async () => []
let dmLoaded = false
async function dmReady() {
  if (dmLoaded) return
  const url = process.env.BILI_DM_LIB
    || pathToFileURL(path.join(HOME_DIR, '.dsh', 'profiles', 'web', 'node_modules', 'dsh-bili-scroll', 'lib', 'dm.mjs')).href
  const m = await import(url)
  loadCred = m.loadCred
  fetchMsgs = m.fetchMsgs
  dmLoaded = true
}
const CFG = path.join(DUTY, 'config.json')
const PERSONA = path.join(DUTY, 'persona.md')
const MIRROR = process.env.BILI_SCORING_MIRROR || path.join(HERE_DIR, 'persona.md')

const argv = process.argv.slice(2)
const has = (k) => argv.includes(k)

// ── 常量 ─────────────────────────────────────────────────────────────────
const SCORE_MIN = -1          // -1 = 特别差
const SCORE_MAX = 11          // 11 = 特别好（会触发提词）
const SUPER = 11
const TERRIBLE = -1
const KW_CAP = 24             // keywords 上限（太多了每轮也只能用一个词）
const LEARN_MIN = 3           // 纯文字评价攒够几条才自动学一次

const ITEM_BV = /\[(\d{1,2})\]([\s\S]{0,400}?)(BV[0-9A-Za-z]{10})/g
/** N=分数 / N：分数 / N 分数（分数 -1~11，允许前后有标点） */
const PAIR = /(?:^|[^\d\w])(\d{1,2})\s*[=:：]\s*(-?\d{1,2})(?!\d)/g
/** 只写文字时的条目号开头：`4 调色板真舒服` / `[4] 调色板真舒服` / `4、…` */
const TEXT_ONLY = /^\s*\[?(\d{1,2})\]?\s*[，,、.。:：\-\s]+([\s\S]+)$/

// 提词时不要的泛词
const STOP = new Set([
  '视频', '这条', '那条', '这个', '那个', '一个', '自己', '就是', '不是', '没有', '真的', '还是',
  '已经', '但是', '所以', '因为', '而且', '感觉', '觉得', '喜欢', '好看', '好听', '太强', '很强',
  '内容', '质量', '节奏', '讲解', '介绍', '分享', '全程', '整部', '看完', '推荐', '值得', '意思',
  '东西', '方面', '部分', '地方', '时候', '一样', '有点', '特别', '非常', '比较', '更', '很', '太',
  '的', '了', '是', '和', '也', '就', '都', '讲', '说', '看', '吧', '啊', '呢',
])

// ── 小工具 ───────────────────────────────────────────────────────────────
const readJson = (f, d) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')) } catch { return d } }
const writeJson = (f, o) => fs.writeFileSync(f, JSON.stringify(o, null, 2) + '\n', 'utf8')
const bjDate = (ts) => new Date((ts || Date.now() / 1000) * 1000 + 8 * 3600e3).toISOString().slice(0, 10)
const bjTime = (ts) => new Date((ts || 0) * 1000 + 8 * 3600e3).toISOString().slice(5, 16).replace('T', ' ')
const clampScore = (n) => (Number.isFinite(n) ? Math.max(SCORE_MIN, Math.min(SCORE_MAX, Math.round(n))) : null)

// ── 跑批留痕（计划任务是没有控制台的，输出只能落文件）────────────────────
const SCORELOG = path.join(DUTY, 'scoring.log')
const trace = []
const T = (s) => { trace.push(String(s)) }
const flushLog = () => {
  if (!trace.length) return
  try {
    const line = `[${new Date().toISOString()}] ${trace.join(' · ')}`
    // 日志别无限长：超过 200KB 就砍一半
    try { if (fs.statSync(SCORELOG).size > 200_000) fs.writeFileSync(SCORELOG, fs.readFileSync(SCORELOG, 'utf8').slice(-100_000), 'utf8') } catch { }
    fs.appendFileSync(SCORELOG, line + '\n', 'utf8')
  } catch { /* 日志写不进去不影响主流程 */ }
}

// ── 台账 ─────────────────────────────────────────────────────────────────
function loadLedger() {
  if (!fs.existsSync(LEDGER)) return []
  return fs.readFileSync(LEDGER, 'utf8').split('\n').filter((l) => l.trim())
    .map((l) => { try { return JSON.parse(l) } catch { return null } }).filter(Boolean)
}

// ── 最长公共子串（提词用）────────────────────────────────────────────────
function longestCommon(a, b, max = 10) {
  let best = { s: '', i: -1, j: -1 }
  for (let i = 0; i < a.length; i++) {
    for (let j = 0; j < b.length; j++) {
      let k = 0
      while (i + k < a.length && j + k < b.length && a[i + k] === b[j + k] && k < max) k++
      if (k > best.s.length) best = { s: a.slice(i, i + k), i, j }
    }
  }
  return best
}

/**
 * 新词是不是"多余"：
 *   · 被已有词包住（已有 `泰拉瑞亚`，又来 `泰拉`）⇒ 多余；
 *   · 只是把已有词多说了一两个字（`泰拉瑞亚` → `泰拉瑞亚啊`）⇒ 也多余；
 *   · 但已有 `泰拉瑞亚` 时，`泰拉瑞亚的电路` 这种**更具体**的是有价值的 ✓
 */
function isRedundant(word, list) {
  return list.some((k) => {
    if (!k) return false
    if (k === word) return true
    if (k.includes(word)) return true
    if (word.includes(k) && word.length - k.length < 2) return true
    return false
  })
}

/**
 * 从「他说好在哪」里提词 ⇒ 加进 keywords 的候选。
 * 思路：**他夸的点通常就在标题里** —— 所以取「理由」和「标题 / UP 名」的公共子串，
 * 既准（一定是这条视频的特征）又不用上分词器。
 */
function extractGoodKeywords(reason, title, up, existing) {
  const src = String(reason || '').trim()
  if (!src) return []
  const pools = [String(title || ''), String(up || '')].filter((s) => s.length >= 2)
  const out = []
  for (const pool of pools) {
    let rest = src
    for (let round = 0; round < 3; round++) {
      const m = longestCommon(rest, pool, 10)
      const w = m.s.replace(/[\s\p{P}]/gu, '')
      if (w.length < 2) break
      rest = rest.replace(m.s, '\u0000')
      // ⭐ 顺着标题把词补全：理由里只说"空岛"，标题写的是"空岛生存？"⇒ 取"空岛生存"
      //    （但最多只往前补 3 个字，免得把整条长标题当关键词）
      let cand = w
      if (m.j >= 0 && pool === String(title || '')) {
        const run = /^[\u4e00-\u9fa5A-Za-z0-9]{2,12}/.exec(pool.slice(m.j))
        if (run && run[0].startsWith(m.s.replace(/[\s\p{P}]/gu, '')) && run[0].length <= w.length + 3) {
          cand = run[0]
        }
      }
      const clean = cand.replace(/^(第|个|集|期|版|部)/, '')
      if (clean.length < 2 || STOP.has(clean)) continue
      if (isRedundant(clean, existing)) continue
      if (isRedundant(clean, out)) continue
      out.push(clean.slice(0, 12))
      if (out.length >= 2) return out
    }
  }
  return out
}

/**
 * 从「他说差在哪」里找出该删的词：现有 keywords 里，出现在理由里的就删。
 * （他说「高数上课太无聊」⇒ 删「高数」；说「标题党」⇒ 没有对应的词，什么都不删）
 */
function extractBadKeywords(reason, existing) {
  const src = String(reason || '').trim()
  if (!src) return []
  return existing.filter((k) => k && src.includes(String(k).trim()))
}

// ══════════════════════════════════════════════════════════════════════════
//  纯文字评价：先缓冲、再学习（2026-11-05 加）
// ══════════════════════════════════════════════════════════════════════════
// 为什么不立刻改关键词：**一句随口的话不该直接动搜索方向**（会带偏）。
// 但也不能白丢 —— 所以：进缓冲区 ⇒ 攒够 / 手点 --learn 时统一学一次：
//   · 他**反复提到**的词（≥2 条评价里都出现）才算数；
//   · 反复提的是好话 ⇒ 加进 keywords；反复提的是抱怨 ⇒ 从 keywords 里删；
//   · 只提过一次的 ⇒ 只写进画像，标注"只出现过一次"，不动作。
//   · 没评分的那些本来就"没有意见"（他不用每条都评）⇒ 缓冲区只收他真写了话的。
const POS_WORDS = ['好', '棒', '强', '绝', '顶', '舒服', '喜欢', '清楚', '讲透', '到位', '好看', '好听',
  '干货', '硬核', '细节', '牛', '稳', '精彩', '有意思', '顺畅', '惊喜', '值', '香', '爽', '佩服']
const NEG_WORDS = ['差', '水', '废话', '无聊', '标题党', '太长', '太短', '拖沓', '没意思', '重复',
  '广告', '带货', '念稿', '敷衍', '失望', '糊弄', '啰嗦', '凑数', '拉胯', '鸡肋', '难受', '看不下去']

/** 这句话是夸还是骂（判断不了就 unknown，unknown 不进关键词） */
function polarityOf(text) {
  const t = String(text || '')
  let p = 0
  for (const w of POS_WORDS) if (t.includes(w)) p++
  for (const w of NEG_WORDS) if (t.includes(w)) p--
  return p > 0 ? 'positive' : p < 0 ? 'negative' : 'unknown'
}

/** 一条评价里，和视频标题重合的短语（最可靠的那部分） */
function titlePhrases(text, title) {
  const out = []
  let rest = String(text || '')
  const pool = String(title || '')
  if (!rest.trim() || !pool) return out
  for (let i = 0; i < 3; i++) {
    const m = longestCommon(rest, pool, 10)
    const w = m.s.replace(/[\s\p{P}]/gu, '')
    if (w.length < 2) break
    rest = rest.replace(m.s, '\u0000')
    if (!STOP.has(w) && !out.includes(w)) out.push(w)
  }
  return out
}

/**
 * 一批语料里「反复出现」的词块 —— 至少出现在 minCount 条评价里。
 * ⚠️ 不能用滑窗 n-gram：那会把「泰拉瑞亚的电路」切成「泰拉瑞亚的电」「拉瑞亚的电路」两个残词
 *    （2026-11-05 演练里就这么翻车过）。改成**两两求最长公共子串**，再合并重叠的。
 */
function repeatedPhrases(texts, minCount = 2, minLen = 3, maxLen = 12) {
  const clean = texts.map((t) => String(t || '').replace(/[\s\p{P}]/gu, ''))
  const hits = new Map()                        // 词 -> 出现在哪几条里
  for (let i = 0; i < clean.length; i++) {
    for (let j = i + 1; j < clean.length; j++) {
      let a = clean[i]
      let b = clean[j]
      for (let guard = 0; guard < 8; guard++) {
        const m = longestCommon(a, b, maxLen)
        if (!m.s || m.s.length < minLen) break
        if (!STOP.has(m.s)) {
          if (!hits.has(m.s)) hits.set(m.s, new Set())
          hits.get(m.s).add(i)
          hits.get(m.s).add(j)
        }
        a = a.slice(0, m.i) + '\u0000' + a.slice(m.i + m.s.length)
        b = b.slice(0, m.j) + '\u0000' + b.slice(m.j + m.s.length)
      }
    }
  }
  const cand = [...hits.entries()].filter(([, s]) => s.size >= minCount).map(([w]) => w)
  cand.sort((x, y) => y.length - x.length || x.localeCompare(y))
  const kept = []
  for (const w of cand) {
    if (kept.some((k) => k.includes(w) || w.includes(k))) continue
    // 和已保留的词高度重叠（共享 ≥3 字）就丢掉，避免"同一个词的两个错位版本"
    if (kept.some((k) => longestCommon(k, w, maxLen).s.length >= Math.min(3, w.length))) continue
    kept.push(w)
  }
  return kept
}

/**
 * 学习一次：把缓冲区里"还没学过"的纯文字评价消化掉。
 * 返回 { learned, repeated:[{word,count,polarity}], added, removed }
 */
function learnBuffer({ dry = false, force = false } = {}) {
  const rows = loadLedger()
  const buf = rows.filter((r) => r.score === null && !r.learned)
  if (!buf.length) return { learned: 0, repeated: [], added: [], removed: [], note: '缓冲区是空的' }
  if (buf.length < LEARN_MIN && !force) {
    return { learned: 0, repeated: [], added: [], removed: [], note: `缓冲区攒了 ${buf.length} 条（满 ${LEARN_MIN} 条才学，或 --learn 立刻学）` }
  }

  const texts = buf.map((r) => String(r.note || ''))
  const repeated = repeatedPhrases(texts).map((word) => {
    const hit = buf.filter((r) => String(r.note || '').includes(word))
    return { word, count: hit.length, polarity: polarityOf(hit.map((r) => r.note).join(' ')) }
  }).filter((x) => x.polarity !== 'unknown' && x.count >= 2)

  const add = repeated.filter((x) => x.polarity === 'positive').map((x) => x.word)
  const remove = repeated.filter((x) => x.polarity === 'negative').map((x) => x.word)

  let realAdded = add
  let realRemoved = remove
  if (!dry) {
    if (add.length || remove.length) {
      const res = applyKeywordPatch({ add, remove, why: '纯文字评价学习', dry: false })
      realAdded = res.added || []
      realRemoved = res.removed || []
    }
    // 标记已学
    const bufKeys = new Set(buf.map((r) => r.bvid + '|' + r.at))
    const next = rows.map((r) => (r.score === null && bufKeys.has(r.bvid + '|' + r.at) ? { ...r, learned: true } : r))
    fs.writeFileSync(LEDGER, next.map((r) => JSON.stringify(r)).join('\n') + '\n', 'utf8')
    // 把这次学到的东西记进 state，画像里要显示
    const st = readJson(STATE, { processed: [] })
    st.promoted = [...(st.promoted || []), ...repeated.map((x) => ({ ...x, at: new Date().toISOString() }))].slice(-40)
    writeJson(STATE, st)
  }
  return { learned: buf.length, repeated, added: realAdded, removed: realRemoved, note: '' }
}

// ── 关键词落盘（直接改插件 config.json，下一轮 refreshCfg 就读到）──────────
function applyKeywordPatch({ add = [], remove = [], why = '', bvid = '', dry = false }) {
  const cfg = readJson(CFG, null)
  if (!cfg) return { ok: false, error: '读不到 config.json' }
  const before = Array.isArray(cfg.keywords) ? cfg.keywords.slice() : []
  let next = before.filter((k) => !remove.includes(k))
  const added = []
  for (const w of add) {
    if (isRedundant(w, next)) continue
    if (next.length >= KW_CAP) break
    next.push(w); added.push(w)
  }
  const removed = before.filter((k) => !next.includes(k))
  if (!added.length && !removed.length) return { ok: true, changed: false, before, next, added, removed }
  if (dry) return { ok: true, changed: true, dry: true, before, next, added, removed }
  cfg.keywords = next
  if (Array.isArray(cfg._set) && !cfg._set.includes('keywords')) cfg._set.push('keywords')
  writeJson(CFG, cfg)
  try {
    fs.appendFileSync(KLOG, JSON.stringify({
      at: new Date().toISOString(), bvid, why: String(why).slice(0, 120), added, removed, keywords: next,
    }) + '\n', 'utf8')
  } catch { /* 记不上不影响主流程 */ }
  return { ok: true, changed: true, before, next, added, removed }
}

// ── 解析一条大号消息 ─────────────────────────────────────────────────────
/**
 * 全角 → 半角（**等长映射**，字符数不变）。
 * ⚠️ 不能用 normalize('NFKC')：那会把中文标点也改掉（`，`→`,`），
 *    等于篡改使用者原话，画像里就会出现被改过的句子 ✗
 * ⚠️ 也不能不归一：中文输入法打的是全角 `＝`/`：`/数字，
 *    2026-11-05 实测「3＝11 有深度」被当成闲聊、11 分直接丢 ✗
 */
const FW_RE = /[\uFF01-\uFF5E]/g
function toHalf(s) {
  return String(s || '')
    .replace(FW_RE, (c) => String.fromCharCode(c.charCodeAt(0) - 0xFEE0))
    .replace(/\u3000/g, ' ')
    .replace(/\u2212/g, '-')
}

/** 返回 [{ n, score|null, reason }] */
function parseMessage(text) {
  const raw = String(text || '').replace(/\r/g, '')
  const t = toHalf(raw)          // 与 raw **等长** ⇒ 下标可以通用，理由一律从 raw 里取
  const pairs = [...t.matchAll(PAIR)]
    .map((m) => ({ n: Number(m[1]), score: clampScore(Number(m[2])), at: m.index, end: m.index + m[0].length }))
    .filter((p) => p.n >= 1 && p.n <= 60 && p.score !== null)

  if (pairs.length) {
    return pairs.map((p, i) => {
      const stop = i + 1 < pairs.length ? pairs[i + 1].at : raw.length
      const reason = raw.slice(p.end, stop).replace(/^[\s,，、;；:：\-—]+/, '').replace(/\n+/g, ' ').trim()
      return { n: p.n, score: p.score, reason }
    })
  }
  // 没有分数 ⇒ 也许只是写了一句评价
  const m = TEXT_ONLY.exec(t)
  if (m) {
    const start = m.index + m[0].length - m[2].length
    return [{ n: Number(m[1]), score: null, reason: raw.slice(start).trim() }]
  }
  return []
}

// ── 从私信里还原每一批的 [N] → BV 清单 ──────────────────────────────────
function buildBatches(msgs) {
  const batches = []      // [{ at, items: Map<n,{bvid,title,up}> }]
  let cur = null
  for (const m of msgs) {
    if (!m.fromMe) continue
    const items = [...m.text.matchAll(ITEM_BV)]
    if (!items.length) continue
    if (!cur || Number(items[0][1]) <= 1) { cur = { at: m.ts, items: new Map() }; batches.push(cur) }
    for (const it of items) {
      const title = String(it[2] || '').replace(/https?:\/\/\S+/g, ' ').replace(/[·\u00b7][^\n]*$/, ' ')
        .replace(/^[\s:：、.\-]+/, '').split('\n')[0].trim().slice(0, 90)
      const up = (/·\s*([^\n·]{2,20})\s*$/.exec(String(it[2] || '').split('\n')[0]) || [])[1] || ''
      cur.items.set(Number(it[1]), { bvid: it[3], title, up: up.trim() })
    }
  }
  return batches
}

function batchForMsg(batches, ts) {
  let pick = null
  for (const b of batches) if (!b.at || b.at <= ts) pick = b
  return pick || batches[batches.length - 1] || null
}

// ── RATINGS 报告 ─────────────────────────────────────────────────────────
const MARK_A = '<!-- RATINGS:BEGIN 由 评分.mjs --report 自动生成，别手改 -->'
const MARK_B = '<!-- RATINGS:END -->'
/** 定位用的前缀（标记尾巴换过版本，只认前缀才不会漏） */
const BEGIN = '<!-- RATINGS:BEGIN'
const END = MARK_B

function writeReport() {
  const rows = loadLedger().slice().sort((a, b) => String(a.at).localeCompare(String(b.at)))
  if (!rows.length) { console.log('台账还是空的。'); return false }
  const txt = rows.filter((r) => r.score === null)
  const promoted = (readJson(STATE, {}) || {}).promoted || []
  // ⚠️ 分数分桶只看真正打过分的：score===null 的 `Number(null)` 是 0，
  //    以前会把纯文字评价全算进"低分" ✗（2026-11-05 演练发现的）
  const scored = rows.filter((r) => r.score !== null)
  const top = scored.filter((r) => Number(r.score) >= 8)
  const low = scored.filter((r) => Number(r.score) <= 3)
  const mid = scored.filter((r) => Number(r.score) > 3 && Number(r.score) < 8)
  const fmt = (r) => `- ${r.score} 分 · ${String(r.title || r.bvid).slice(0, 46)}${r.note && r.note !== '私信' && r.note !== '私信补录' ? ' —— ' + String(r.note).slice(0, 40) : ''}`
  const kws = (readJson(CFG, {}) || {}).keywords || []
  const block = [
    MARK_A,
    `# 我给过的评分（共 ${rows.length} 条，越新越算数）`,
    '',
    '> 口径：**11 分 = 特别好**（他说了好在哪，那些词已经被加进搜索关键词）；',
    '> **-1 分 = 特别差**（他说了差在哪，相关词已经从搜索关键词里删掉）；',
    '> **纯文字评价**没有分数，只有他的一句话。**没评的那条 = 没意见**，别当成差评。',
    '',
    `## 高分（≥8，${top.length} 条）—— 多给我这种`,
    ...top.slice(-14).reverse().map(fmt),
    '',
    `## 低分（≤3，${low.length} 条）—— 别再推这种`,
    ...low.slice(-14).reverse().map(fmt),
    '',
    `## 中评（4-7，${mid.length} 条）`,
    mid.length ? `- 平均 ${(mid.reduce((s, r) => s + Number(r.score), 0) / mid.length).toFixed(1)} 分` : '-（还没有）',
    '',
    `## 他随口说的（纯文字评价，${txt.length} 条 · 缓冲区）`,
    ...(txt.length
      ? txt.slice(-10).reverse().map((r) => `- ${r.polarity === 'positive' ? '👍' : r.polarity === 'negative' ? '👎' : '·'} 「${String(r.note).slice(0, 46)}」· ${String(r.title || r.bvid).slice(0, 30)}${r.learned ? '（已学）' : '（待学）'}`)
      : ['-（还没有）']),
    '',
    '## 缓冲区学到的词（同一条评价里提一次不算，**≥2 条都提到**才算数）',
    ...(promoted.length
      ? promoted.slice(-8).reverse().map((p) => `- ${p.polarity === 'positive' ? '👍 加权' : '👎 降权'} · 「${p.word}」×${p.count}`)
      : ['-（还没学到）']),
    '',
    `## 现在的搜索关键词（${kws.length}）`,
    kws.length ? kws.map((k) => '`' + k + '`').join(' · ') : '-（空）',
    '',
    '⚠️ **判据**：高分特征 → 加权；低分特征 → 明显降权甚至排除。11 分那几条是"就是这个味"，优先照它去找。',
    MARK_B,
  ].join('\n')

  let wrote = 0
  for (const f of [PERSONA, MIRROR]) {
    if (!fs.existsSync(f)) continue
    let txt = fs.readFileSync(f, 'utf8')
    // ⭐ 先把这个文件里**所有**旧的 RATINGS 块剥掉再写 —— 换过脚本（打分.mjs → 评分.mjs）时
    //    标记文字的尾巴不一样，只按完整标记找会漏，结果就是堆出两份块 ✗
    for (;;) {
      const i = txt.indexOf(BEGIN)
      if (i < 0) break
      const j = txt.indexOf(END, i)
      txt = txt.slice(0, i) + (j < 0 ? '' : txt.slice(j + END.length))
    }
    fs.writeFileSync(f, txt.replace(/\s+$/, '') + '\n\n' + block + '\n', 'utf8')
    wrote++
  }
  console.log(`画像已更新（${wrote} 份）｜台账 ${rows.length} 条：高 ${top.length} · 中 ${mid.length} · 低 ${low.length} · 纯文字 ${rows.filter((r) => r.score === null).length}`)
  console.log('关键词：' + (kws.length ? kws.join(' · ') : '（空）'))
  return true
}

// ── 主流程 ───────────────────────────────────────────────────────────────
async function ingest(dry) {
  const st = readJson(STATE, { processed: [] })
  const done = new Set(st.processed || [])
  await dmReady()
  const cred = loadCred(DUTY)
  const msgs = await fetchMsgs(cred, OWNER, 50)
  const batches = buildBatches(msgs)

  const rows = []
  let skipped = 0
  for (const m of msgs) {
    if (m.fromMe) continue
    if (done.has(m.key)) { skipped++; continue }
    const parsed = parseMessage(m.text)
    if (!parsed.length) continue
    const batch = batchForMsg(batches, m.ts)
    if (!batch) continue
    for (const p of parsed) {
      const hit = batch.items.get(p.n)
      if (!hit) { console.log(`  [!] ${bjTime(m.ts)} 第 ${p.n} 条在这批清单里找不到，跳过`); continue }
      rows.push({
        at: new Date((m.ts || Date.now() / 1000) * 1000).toISOString(),
        date: bjDate(m.ts), bvid: hit.bvid, title: hit.title || hit.bvid,
        score: p.score, note: p.reason || '私信', src: 'dm', msgKey: m.key,
        // 纯文字评价进缓冲区：带上极性，等攒够了一起学（不立刻改关键词）
        ...(p.score === null ? { polarity: polarityOf(p.reason), learned: false } : {}),
      })
    }
    if (!dry) done.add(m.key)
  }

  if (!rows.length) {
    console.log(`私信里没有新的评价（已处理 ${done.size} 条消息，跳过 ${skipped} 条旧的）。`)
    T(`无新评价（私信 ${msgs.length} 条，已处理 ${done.size}）`)
    return 0
  }

  // ⭐ 双重去重：消息 id 之外，再看台账里有没有「同一条视频同一天同一个分数」——
  //    这样历史数据（没有 msgKey 的那些）重跑也不会重复记账 ✓
  const seen = new Set(loadLedger().map((r) => `${r.bvid}|${r.date}|${r.score}`))
  const freshRows = []
  for (const r of rows) {
    const k = `${r.bvid}|${r.date}|${r.score}`
    if (seen.has(k)) { console.log(`  （已记过，跳过）${r.bvid} ${r.date} ${r.score} 分`); continue }
    seen.add(k)
    freshRows.push(r)
  }
  rows.length = 0
  rows.push(...freshRows)
  if (!rows.length) { console.log('这批评价台账里都有了，不重复记。'); T('这批已记过'); return 0 }

  console.log(`\n=== 解析到 ${rows.length} 条${dry ? '（预览）' : ''} ===`)
  const kwPlan = { add: [], remove: [], notes: [] }
  for (const r of rows) {
    const tag = r.score === null ? '文字' : r.score === SUPER ? '★11' : r.score === TERRIBLE ? '✗-1' : `${r.score} 分`
    console.log(`  ${String(tag).padStart(5)}  ${r.bvid}  ${String(r.title).slice(0, 34)}${r.note && r.note !== '私信' ? '  「' + String(r.note).slice(0, 30) + '」' : ''}`)
    const cur = (readJson(CFG, {}) || {}).keywords || []
    if (r.score === SUPER && r.note && r.note !== '私信') {
      const add = extractGoodKeywords(r.note, r.title, '', cur.concat(kwPlan.add).filter((k) => !kwPlan.remove.includes(k)))
      if (add.length) { kwPlan.add.push(...add); kwPlan.notes.push(`11 分加词：${add.join('、')}（来自「${r.note.slice(0, 24)}」）`) }
    }
    if (r.score === TERRIBLE && r.note && r.note !== '私信') {
      const bad = extractBadKeywords(r.note, cur.filter((k) => !kwPlan.remove.includes(k)))
      if (bad.length) { kwPlan.remove.push(...bad); kwPlan.notes.push(`-1 分删词：${bad.join('、')}（来自「${r.note.slice(0, 24)}」）`) }
    }
  }

  if (kwPlan.notes.length) {
    console.log('\n=== 关键词变动 ===')
    for (const n of kwPlan.notes) console.log('  · ' + n)
  }
  const kwRes = applyKeywordPatch({ add: kwPlan.add, remove: kwPlan.remove, why: '私信评价', dry })
  if (kwRes.changed) {
    console.log(`  关键词：${kwRes.before.join(' · ') || '（空）'}  →  ${kwRes.next.join(' · ') || '（空）'}${dry ? '   （预览）' : ''}`)
  }

  if (dry) { console.log('\n--dry：什么都没写。'); return rows.length }

  fs.appendFileSync(LEDGER, rows.map((r) => JSON.stringify(r)).join('\n') + '\n', 'utf8')
  writeJson(STATE, { processed: [...done], lastRun: new Date().toISOString() })
  console.log(`\n已记账 ${rows.length} 条到 ratings.jsonl`)
  T(`记账 ${rows.length} 条` + (kwRes.changed ? `｜关键词 ${kwRes.before.join('/')}→${kwRes.next.join('/')}` : ''))

  // ⭐ 纯文字评价：先缓冲，攒够了再学（学完才动关键词 + 写进画像）
  const lr = learnBuffer()
  if (lr.learned) {
    console.log(`\n=== 缓冲区学习：消化了 ${lr.learned} 条纯文字评价 ===`)
    for (const x of lr.repeated) {
      const tag = x.polarity === 'positive' ? '👍' : '👎'
      console.log(`  ${tag} 「${x.word}」出现 ${x.count} 次`)
    }
    if (lr.added.length) console.log(`  → 加进关键词：${lr.added.join('、')}`)
    if (lr.removed.length) console.log(`  → 从关键词删掉：${lr.removed.join('、')}`)
    T(`学习 ${lr.learned} 条：${lr.repeated.map((x) => x.word).join('/') || '无可提炼词'}`)
  } else if (lr.note) {
    console.log(`\n  ${lr.note}`)
  }

  writeReport()
  return rows.length
}

// ── 入口 ─────────────────────────────────────────────────────────────────
const main = async () => {
  if (has('--list')) {
    const rows = loadLedger().slice(-40)
    if (!rows.length) { console.log('台账是空的。'); return }
    console.log(`\n  台账（最近 ${rows.length} 条）`)
    console.log('  ' + '─'.repeat(78))
    for (const r of rows) {
      const s = r.score === null ? '文字' : r.score === 11 ? ' ★11' : r.score === -1 ? ' ✗-1' : String(r.score).padStart(3) + ' 分'
      console.log(`  ${r.date}  ${s.padEnd(6)} ${r.bvid}  ${String(r.title || '').slice(0, 34)}`)
    }
    const nums = rows.filter((r) => r.score !== null)
    console.log('  ' + '─'.repeat(78))
    console.log(`  共 ${rows.length} 条　均分 ${nums.length ? (nums.reduce((s, r) => s + Number(r.score), 0) / nums.length).toFixed(2) : '-'}`)
    return
  }
  if (has('--report')) { writeReport(); return }
  if (has('--learn')) {
    // node 评分.mjs --learn          立刻把缓冲区的纯文字评价学一遍
    // node 评分.mjs --learn --dry    只看会学到什么
    const lr = learnBuffer({ dry: has('--dry'), force: true })
    if (lr.learned) {
      console.log(`\n消化了 ${lr.learned} 条纯文字评价`)
      for (const x of lr.repeated) console.log(`  ${x.polarity === 'positive' ? '👍' : '👎'} 「${x.word}」×${x.count}`)
      if (lr.added.length) console.log(`加进关键词：${lr.added.join('、')}`)
      if (lr.removed.length) console.log(`从关键词删掉：${lr.removed.join('、')}`)
      if (has('--dry')) console.log('（--dry：没写任何东西）')
      else writeReport()
    } else {
      console.log(lr.note)
    }
    return
  }
  if (has('--kw')) {
    // node 评分.mjs --kw add 我的世界   /   node 评分.mjs --kw del 高数
    const a = argv.slice(argv.indexOf('--kw') + 1).filter((x) => !x.startsWith('--'))
    const op = String(a[0] || '').toLowerCase()
    const words = a.slice(1).map((s) => s.trim()).filter(Boolean)
    if (!['add', 'del', 'rm', 'remove'].includes(op) || !words.length) {
      console.log('用法：node 评分.mjs --kw add 我的世界   或   node 评分.mjs --kw del 高数')
      return
    }
    const res = applyKeywordPatch(op === 'add' ? { add: words, why: '手动 --kw' } : { remove: words, why: '手动 --kw' })
    if (!res.ok) { console.log('失败：', res.error); return }
    console.log(`关键词：${res.before.join(' · ') || '（空）'}  →  ${res.next.join(' · ') || '（空）'}`)
    if (res.changed) writeReport()
    return
  }
  if (has('--set')) {
    const a = argv.slice(argv.indexOf('--set') + 1).filter((x) => !x.startsWith('--'))
    const n = Number(a[0]); const score = clampScore(Number(a[1]))
    if (!n || score === null) { console.log('用法：node 评分.mjs --set 3 10'); return }
    await dmReady()
    const cred = loadCred(DUTY)
    const msgs = await fetchMsgs(cred, OWNER, 50)
    const batch = buildBatches(msgs)
    const last = batch[batch.length - 1]
    const hit = last?.items.get(n)
    if (!hit) { console.log(`最近一批里没有第 ${n} 条`); return }
    const row = { at: new Date().toISOString(), date: bjDate(), bvid: hit.bvid, title: hit.title, score, note: '手动', src: 'manual' }
    fs.appendFileSync(LEDGER, JSON.stringify(row) + '\n', 'utf8')
    console.log('已记：', row.bvid, score, '分')
    writeReport()
    return
  }
  await ingest(has('--dry'))
}

export {
  parseMessage, extractGoodKeywords, extractBadKeywords, applyKeywordPatch, writeReport, loadLedger,
  polarityOf, repeatedPhrases, titlePhrases, learnBuffer,
}

if (import.meta.main) {
  main()
    .then(() => { T('完成'); flushLog() })
    .catch((e) => { T('出错：' + (e?.message ?? e)); flushLog(); console.error('出错了：', e?.message ?? e) })
}
