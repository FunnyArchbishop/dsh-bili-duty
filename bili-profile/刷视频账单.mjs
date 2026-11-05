#!/usr/bin/env node
/**
 * 刷视频账单.mjs —— 「刷B站」值班轮的消耗查询器
 *
 * 数据来源：DSH 的会话记录（多帧 zstd 的 jsonl），只统计 cwd = ~/.dsh/bili-duty 的会话
 *          —— 也就是插件自己 spawn 出来的那些值班轮，不含你和 AI 聊天的主会话。
 * 计价：DeepSeek 官方价目表（元 / 百万 tokens），按每条 usage 记录的时间戳分峰谷。
 *
 * 用法：
 *   node 刷视频账单.mjs              今天
 *   node 刷视频账单.mjs --today      同上
 *   node 刷视频账单.mjs --yesterday  昨天
 *   node 刷视频账单.mjs --month      本月
 *   node 刷视频账单.mjs --since 2026-10-29
 *   node 刷视频账单.mjs --all        全部
 *   node 刷视频账单.mjs --json       机器可读
 *   node 刷视频账单.mjs --detail     逐轮明细（默认开着）
 *
 * ⚠️ 计价口径
 *   ✅ 只给**走 DeepSeek 官方路由**（provider = deepseek-official）的轮次计价；
 *      走外部网关（2026-10-29 起值班轮默认走「清华给的 DeepSeek 接口」
 *      provider = tsinghua-api）的轮次按**不计价**处理，只统计 token 与步数
 *      —— 那条链路的钱不从你 DeepSeek 账户出，混在一起算就是虚报。
 *   deepseek-flash（含旧名 deepseek-v4-flash / -vision-exp）：
 *     空闲时段  缓存命中 ¥0.02/M ｜ 未命中 ¥1/M ｜ 输出 ¥4/M
 *     高峰时段  缓存命中 ¥0.04/M ｜ 未命中 ¥2/M ｜ 输出 ¥8/M
 *   高峰 = 北京时间 周一至周五 9:00-12:00、14:00-18:00
 *   （法定节假日按空闲计 —— 本脚本没接节假日表，那些天会略微高估）
 */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';

// ── 价格（元 / 百万 tokens）───────────────────────────────────────────────
const P = {
  off:  { hit: 0.02, miss: 1, out: 4 },
  peak: { hit: 0.04, miss: 2, out: 8 },
};

// ── 会话根目录 ───────────────────────────────────────────────────────────
const DSH_HOME = process.env.DSH_HOME || path.join(os.homedir(), '.dsh');
const SESSIONS = path.join(DSH_HOME, 'sessions');
const DUTY_HOME = path.join(DSH_HOME, 'bili-duty');

// ── 参数 ─────────────────────────────────────────────────────────────────
const argv = process.argv.slice(2);
const has = (k) => argv.includes(k);
const pickArg = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null; };

// ── 峰谷判定（北京时间）──────────────────────────────────────────────────
function isPeak(ms) {
  const d = new Date(ms + 8 * 3600 * 1000);           // 转北京时间
  const wd = d.getUTCDay();                            // 0=周日
  if (wd === 0 || wd === 6) return false;              // 周末全天空闲
  const h = d.getUTCHours() + d.getUTCMinutes() / 60;
  return (h >= 9 && h < 12) || (h >= 14 && h < 18);
}

// ── 多帧 zstd 解压（DSH 的 session.jsonl.zstd 是逐条追加的多个 frame）─────
const MAGIC = Buffer.from([0x28, 0xb5, 0x2f, 0xfd]);
function decompressAll(buf) {
  const idx = [];
  let i = 0;
  while ((i = buf.indexOf(MAGIC, i)) !== -1) { idx.push(i); i += 4; }
  let out = '';
  for (let k = 0; k < idx.length; k++) {
    const s = idx[k];
    const e = k + 1 < idx.length ? idx[k + 1] : buf.length;
    try { out += zlib.zstdDecompressSync(buf.subarray(s, e)).toString('utf8'); } catch { /* 半截帧，跳过 */ }
  }
  return out;
}

// ── 找出所有值班轮会话 ───────────────────────────────────────────────────
// ⚡ 先在**路径**上筛掉不相干的会话（DSH 用 cwd 给 sessions 目录命名，
//    值班轮那棵一定带 "bili-duty"），避免把几十个无关会话全解压一遍。
function listDutySessions() {
  const out = [];
  const collect = (d) => {
    let es;
    try { es = fs.readdirSync(d, { withFileTypes: true }); } catch { return; }
    for (const x of es) {
      const q = path.join(d, x.name);
      if (x.isDirectory()) collect(q);
      else if (x.name === 'session.jsonl.zstd') out.push(q);
    }
  };
  const walk = (dir) => {
    let entries;
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (!e.isDirectory()) continue;
      const p = path.join(dir, e.name);
      if (/bili-duty/i.test(e.name)) collect(p);   // 命中就整棵收下，不再往下钻
      else walk(p);
    }
  };
  walk(SESSIONS);
  return out;
}

function readSession(file) {
  const st = fs.statSync(file);
  const txt = decompressAll(fs.readFileSync(file));
  const lines = txt.split('\n').filter(Boolean);
  let meta = {};
  try { meta = JSON.parse(lines[0] || '{}'); } catch { /* ignore */ }
  // 只保留值班轮：cwd 指向插件家目录
  const cwd = String(meta.cwd || '');
  const norm = (s) => s.replace(/[\\/]+/g, '/').toLowerCase();
  if (!norm(cwd).endsWith('/.dsh/bili-duty')) return null;

  let hit = 0, miss = 0, outp = 0, reasoning = 0, steps = 0, cost = 0;
  let peakTok = 0, offTok = 0, first = null, last = null;

  // ── 路由识别（决定这一轮算不算钱）─────────────────────────────────────
  // DeepSeek 官方才按官方价目表算；外部网关（清华 / 同济 …）不从这里扣钱。
  const provs = new Set();
  for (const m of txt.matchAll(/"(?:provider|providerId)"\s*:\s*"([^"]{2,40})"/g)) provs.add(m[1]);
  const route = [...provs].find((p) => p !== 'session-title-first-prompt-llm') || 'unknown';
  const billed = route === 'unknown' || route === 'deepseek-official';

  for (const l of lines) {
    if (!l.includes('"type":"usage"')) continue;
    let o;
    try { o = JSON.parse(l); } catch { continue; }
    const u = o?.data?.chunk?.usage;
    if (!u) continue;
    const t = o.time || st.mtime.getTime();
    const k = isPeak(t) ? P.peak : P.off;
    const i1 = u.inputTokens || 0;
    const c1 = u.cacheReadTokens || 0;
    const o1 = u.outputTokens || 0;
    hit += c1; miss += i1; outp += o1; reasoning += u.reasoningTokens || 0; steps++;
    if (billed) cost += (i1 / 1e6) * k.miss + (c1 / 1e6) * k.hit + (o1 / 1e6) * k.out;
    if (isPeak(t)) peakTok += i1 + c1 + o1; else offTok += i1 + c1 + o1;
    if (first === null || t < first) first = t;
    if (last === null || t > last) last = t;
  }

  return {
    id: String(meta.id || path.basename(path.dirname(file))),
    startedAt: first ?? st.mtime.getTime(),
    endedAt: last ?? st.mtime.getTime(),
    steps, hit, miss, outp, reasoning,
    peakTok, offTok,
    route, billed,
    cost,
    crashed: steps === 0,
  };
}

// ── 挑了几条：从判重表统计（比日报可靠 —— 日报有漏写的老 bug）──────────────
function picksByDay() {
  const map = new Map();
  const f = path.join(DUTY_HOME, 'seen.md');
  if (!fs.existsSync(f)) return map;
  for (const line of fs.readFileSync(f, 'utf8').split('\n')) {
    const m = line.match(/^\|\s*(\d{4}-\d{2}-\d{2})\s*\|[^|]*\|[^|]*\|[^|]*\|\s*挑了\s*\|/);
    if (m) map.set(m[1], (map.get(m[1]) || 0) + 1);
  }
  return map;
}

// ── 时间窗口 ─────────────────────────────────────────────────────────────
function beijingDayStart(offsetDays = 0) {
  // 返回「北京时间 offsetDays 天前那天 00:00」对应的 UTC 毫秒
  const nowBj = new Date(Date.now() + 8 * 3600 * 1000);
  const y = nowBj.getUTCFullYear(), m = nowBj.getUTCMonth(), d = nowBj.getUTCDate();
  const bjMidnightUtc = Date.UTC(y, m, d) - 8 * 3600 * 1000;
  return bjMidnightUtc + offsetDays * 86400 * 1000;
}

let since = null, until = null, label = '';
if (has('--all')) { label = '全部'; }
else if (has('--month')) {
  const nowBj = new Date(Date.now() + 8 * 3600 * 1000);
  since = Date.UTC(nowBj.getUTCFullYear(), nowBj.getUTCMonth(), 1) - 8 * 3600 * 1000;
  label = `${nowBj.getUTCFullYear()}-${String(nowBj.getUTCMonth() + 1).padStart(2, '0')} 本月`;
} else if (has('--yesterday')) {
  since = beijingDayStart(-1); until = beijingDayStart(0); label = '昨天';
} else if (pickArg('--since')) {
  since = new Date(pickArg('--since') + 'T00:00:00+08:00').getTime();
  label = `自 ${pickArg('--since')}`;
} else {
  since = beijingDayStart(0); until = beijingDayStart(1); label = '今天';
}

// ── 汇总 ─────────────────────────────────────────────────────────────────
const sessions = listDutySessions().map(readSession).filter(Boolean)
  .filter((s) => {
    const t = s.endedAt;
    if (since !== null && t < since) return false;
    if (until !== null && t >= until) return false;
    return true;
  })
  .sort((a, b) => a.startedAt - b.startedAt);

const picks = picksByDay();
const A = { cost: 0, steps: 0, hit: 0, miss: 0, outp: 0, crashed: 0, peakTok: 0, offTok: 0, freeRounds: 0, freeTok: 0 };
for (const s of sessions) {
  A.steps += s.steps; A.hit += s.hit; A.miss += s.miss;
  A.outp += s.outp; A.peakTok += s.peakTok; A.offTok += s.offTok;
  if (s.crashed) A.crashed++;
  if (s.billed) A.cost += s.cost;
  else { A.freeRounds++; A.freeTok += s.hit + s.miss + s.outp; }
}
/** 路由标签：只给「不从 DeepSeek 账户扣钱」的轮次上标签，官方轮次留空 */
const routeTag = (s) => {
  if (s.billed) return '';
  if (s.route === 'tsinghua-api') return '清华';
  if (s.route === 'tongji') return '同济';
  return s.route === 'unknown' ? '?' : s.route.replace(/-api$/, '');
};

// 挑中条数：判重表按**天**记，所以按窗口汇总，不下发到每一轮
let A_picks = 0;
for (const [day, n] of picks) {
  const t = new Date(day + 'T00:00:00+08:00').getTime();
  if (since !== null && t < since) continue;
  if (until !== null && t >= until) continue;
  A_picks += n;
}
A.picks = A_picks;

if (has('--json')) {
  console.log(JSON.stringify({
    window: label,
    sessions: sessions.map((s) => ({
      id: s.id,
      startedAt: new Date(s.startedAt + 8 * 3600 * 1000).toISOString().replace('Z', '+08:00'),
      steps: s.steps, hitTokens: s.hit, missTokens: s.miss, outputTokens: s.outp,
      peakTokens: s.peakTok, offTokens: s.offTok,
      route: s.route, billed: s.billed,
      costYuan: Number(s.cost.toFixed(6)), crashed: s.crashed,
    })),
    total: {
      rounds: sessions.length,
      crashed: A.crashed,
      steps: A.steps,
      hitTokens: A.hit, missTokens: A.miss, outputTokens: A.outp,
      peakTokens: A.peakTok, offTokens: A.offTok,
      picks: A.picks,
      billedRounds: sessions.length - A.freeRounds,
      freeRounds: A.freeRounds,
      freeTokens: A.freeTok,
      costYuan: Number(A.cost.toFixed(6)),
      perRoundYuan: sessions.length ? Number((A.cost / sessions.length).toFixed(6)) : 0,
      perPickYuan: A.picks ? Number((A.cost / A.picks).toFixed(6)) : null,
    },
  }, null, 2));
  process.exit(0);
}

// ── 人读格式 ─────────────────────────────────────────────────────────────
const f = (n) => n.toLocaleString('en-US');
const yuan = (n) => '¥' + n.toFixed(4);
const bj = (ms) => new Date(ms + 8 * 3600 * 1000).toISOString().slice(0, 16).replace('T', ' ');

console.log('');
console.log('  刷视频账单 · ' + label);
console.log('  ' + '─'.repeat(74));

if (!sessions.length) {
  console.log('  这个区间没有值班轮记录。');
  console.log('');
  process.exit(0);
}

let dayPicks = 0;
console.log('  时间(北京)        峰谷 路由  步数      未命中       缓存读       输出          花费');
console.log('  ' + '─'.repeat(84));
for (const s of sessions) {
  const mixed = s.steps === 0 ? '-' : s.peakTok > 0 && s.offTok > 0 ? '混合' : s.peakTok > 0 ? '高峰' : '空闲';
  console.log(
    '  ' + bj(s.startedAt).padEnd(18) +
    mixed.padEnd(5) +
    routeTag(s).padEnd(5) +
    String(s.steps).padStart(4) +
    f(s.miss).padStart(10) +
    f(s.hit).padStart(12) +
    f(s.outp).padStart(11) +
    (s.billed ? yuan(s.cost) : '免费').padStart(10),
  );
}
console.log('  ' + '─'.repeat(84));
console.log(
  '  ' + '合计'.padEnd(28) +
  String(A.steps).padStart(4) +
  f(A.miss).padStart(10) +
  f(A.hit).padStart(12) +
  f(A.outp).padStart(11) +
  yuan(A.cost).padStart(10),
);
console.log('');
console.log(`  轮次 ${sessions.length}（其中失败 ${A.crashed}）` +
  (A.picks ? `　挑中 ${A.picks} 条（判重表口径）` : '') +
  `　DeepSeek 官方口径合计 ${yuan(A.cost)}`);
if (A.freeRounds) {
  console.log(`  另有 ${A.freeRounds} 轮走外部网关（不计价，${f(A.freeTok)} tokens）` +
    `　→ 只统计，不进上面的钱数`);
}
if (sessions.length) {
  const okRounds = sessions.length - A.crashed;
  if (okRounds > 0) process.stdout.write(`  每轮均价 ${yuan(A.cost / okRounds)}`);
  else process.stdout.write('  每轮均价 -（全是失败轮）');
  if (A.picks) process.stdout.write(`　每条 ${yuan(A.cost / A.picks)}`);
  console.log('');
}
const tok = A.hit + A.miss + A.outp;
if (tok) {
  const cHit = 0; // 分项成本在 --json 里给，这里只给占比口径
  console.log(`  token：缓存命中 ${f(A.hit)}　未命中 ${f(A.miss)}　输出 ${f(A.outp)}`);
  console.log(`  峰谷：高峰 ${f(A.peakTok)}　空闲 ${f(A.offTok)}` +
    (A.peakTok ? `　→ 挪到空闲时段可省约 ${yuan(A.cost * 0.5)}` : ''));
}
console.log('');
console.log(`  数据源 ${SESSIONS}`);
console.log(`  计价   只算 provider=deepseek-official 的轮次：闲时 ¥1/¥0.02/¥4　峰时 ¥2/¥0.04/¥8（元每百万，未命中/命中/输出）`);
console.log('');
