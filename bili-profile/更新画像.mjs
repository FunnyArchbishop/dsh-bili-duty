#!/usr/bin/env node
/**
 * 更新画像.mjs —— B站 用户画像增量更新器
 *
 * 基线在 BASELINE.json 的 profileBaseline（2026-10-29）。
 * 默认只分析 fav_time > 基线 的收藏，并把主题分布和基线对比，标出「冒头 / 升温 / 冷却 / 消退」。
 *
 * 用法：
 *   node 更新画像.mjs                 # 增量（默认）
 *   node 更新画像.mjs --since 2026-11-15
 *   node 更新画像.mjs --deep          # 额外深页抽样，用来判断「长跨度」兴趣
 *   node 更新画像.mjs --uid <你的uid> # 校验登录的是不是这个号
 *
 * 输出：终端摘要 + 画像-增量-<今天>.md
 * 只读网、只写本目录。凭证全程留在进程内存，不落盘。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BASE_FILE = path.join(HERE, 'BASELINE.json');
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const HDR = { 'user-agent': UA, referer: 'https://www.bilibili.com/' };
const DEFAULT_FOLDER = 827971601;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- 主题分类表（与画像 v2 一致，改这里要同步 BASELINE.json）----------
const TOPICS = [
  ['东方Project', /东方|幻想乡|恋恋|灵梦|魔理沙|古明地|八云|咲夜|妖梦|芙兰|永琳|蕾米|同人/],
  ['绘画过程', /绘画|作画|线稿|上色|板绘|画法|临摹|速涂|画一只|画成|手书|分镜|live2d|vts/],
  ['原神', /原神|纳西妲|刻晴|芙宁娜|逐月节|菲比|茜特菈莉|胡桃|雷电|神里|甘雨|钟离|温迪|可莉|心海|夜兰|一斗|宵宫|八重/],
  ['泰拉瑞亚', /泰拉|瑞亚|terraria|灾厄/],
  ['学习/升学', /高数|线代|四级|六级|考研|专业|论文|教程|考试|python|算法|复习|笔记|大学/],
  ['我的世界', /我的世界|minecraft|籽岷|红石/],
  ['音乐', /钢琴|翻唱|吉他|歌曲|演唱|cover|弹唱|编曲/],
  ['马尔福/HP', /马尔福|哈利|霍格沃茨|波特/],
  ['周杰伦', /周杰伦|杰伦|jay/i],
  ['美食', /料理|做饭|蒸|炒|煮|菜谱|美食|咖啡/],
  ['ASMR助眠', /asmr|助眠|掏耳|耳骚|催眠|白噪音/],
  ['崩铁', /星穹铁道|星铁|白厄|流萤|黄泉|砂金/],
  ['绝区零', /绝区零|小千夏|艾莲|朱鸢|青衣/],
  ['Gal/AVG', /gal|视觉小说|常轨|妃爱|魔女|女主|生肉|补丁|汉化/],
];
const DEAD = /已失效|失效视频/;

// ---------- 参数 ----------
const argv = process.argv.slice(2);
const pickArg = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null; };
const DEEP = argv.includes('--deep');
const WANT_UID = Number(pickArg('--uid') || 0);

const BASE = JSON.parse(fs.readFileSync(BASE_FILE, 'utf8'));
const SINCE = pickArg('--since') || BASE.profileBaseline;
const TODAY = new Date().toISOString().slice(0, 10);

console.log('基线日 :', BASE.profileBaseline);
console.log('本次窗口: fav_time >', SINCE);
console.log('模式    :', DEEP ? '增量 + 深页抽样' : '增量');

// ---------- 网络 ----------
async function get(url, cookie) {
  const h = { ...HDR };
  if (cookie) h.cookie = cookie;
  const r = await fetch(url, { headers: h });
  const t = await r.text();
  let j = null;
  try { j = JSON.parse(t); } catch { /* 非 JSON */ }
  return { j, r, t };
}

async function login() {
  let buvid = '';
  try {
    const o = await get('https://api.bilibili.com/x/frontend/finger/spi');
    if (o.j?.data) buvid = `buvid3=${o.j.data.b_3}; buvid4=${o.j.data.b_4}`;
  } catch { /* 拿不到就算了 */ }

  const gen = await get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate');
  if (!gen.j?.data) { console.log('GEN_FAIL'); process.exit(2); }
  const key = gen.j.data.qrcode_key;
  console.log('\n=== 请用手机 B站 App 扫码 ===');
  console.log('SCAN_URL ' + gen.j.data.url);
  console.log('WAITING...');

  const t0 = Date.now();
  while (Date.now() - t0 < 8 * 60 * 1000) {
    await sleep(2500);
    const p = await get('https://passport.bilibili.com/x/passport-login/web/qrcode/poll?qrcode_key=' + encodeURIComponent(key));
    const code = p.j?.data?.code;
    if (code === 0) {
      let ck = (p.r.headers.getSetCookie?.() || []).map((s) => s.split(';')[0]).join('; ');
      if (!ck && p.j.data.url) {
        const q = p.j.data.url.split('?')[1] || '';
        ck = q.split('&').filter((x) => x && x.indexOf('gourl') !== 0)
          .map((kv) => { const i = kv.indexOf('='); return kv.slice(0, i) + '=' + decodeURIComponent(kv.slice(i + 1)); })
          .join('; ');
      }
      if (buvid) ck = ck + '; ' + buvid;
      return ck;
    }
    if (code === 86038) { console.log('QR_EXPIRED 二维码过期，重跑一次'); process.exit(3); }
  }
  console.log('NO_COOKIE 没等到扫码');
  process.exit(4);
}

// ---------- 主流程 ----------
const cookie = await login();
const nav = await get('https://api.bilibili.com/x/web-interface/nav', cookie);
if (!nav.j?.data?.mid) { console.log('NAV_FAIL ' + JSON.stringify(nav.j).slice(0, 300)); process.exit(5); }
const UID = nav.j.data.mid;
const UNAME = nav.j.data.uname;
console.log(`LOGIN_OK ${UNAME} uid=${UID}`);
if (WANT_UID && UID !== WANT_UID) {
  console.log(`⚠️ 登录的 uid=${UID} 和期望的 ${WANT_UID} 不一致 —— 后续数据会污染画像，已中止`);
  process.exit(6);
}

// 拉默认收藏夹，按收藏时间倒序，直到本页最旧一条 <= SINCE
const items = [];
let page = 1;
let hitBoundary = false;
while (page <= 60) {
  const r = await get(
    `https://api.bilibili.com/x/v3/fav/resource/list?media_id=${DEFAULT_FOLDER}&pn=${page}&ps=20&platform=web&order=mtime`,
    cookie,
  );
  const d = r.j?.data;
  if (!d?.medias) { console.log(`PAGE_FAIL pn=${page} code=${r.j?.code} msg=${r.j?.message}`); break; }
  for (const m of d.medias) {
    const ts = m.fav_time ? new Date(m.fav_time * 1000).toISOString().slice(0, 10) : '';
    items.push({ d: ts, t: (m.title || '').replace(/[\t\n\r]/g, ' '), u: m.upper?.name || '', b: m.bvid || '' });
  }
  const oldest = d.medias.reduce((a, m) => {
    const s = new Date((m.fav_time || 0) * 1000).toISOString().slice(0, 10);
    return s < a ? s : a;
  }, '9999-99-99');
  if (oldest <= SINCE) { hitBoundary = true; break; }
  if (!d.has_more) break;
  page++;
  await sleep(320);
}
console.log(`拉取 ${items.length} 条（到 pn=${page}，${hitBoundary ? '已触到基线边界' : '未触到边界'}）`);

// 深页抽样（可选）：判断长跨度
const deepSamples = [];
if (DEEP) {
  for (const pn of [40, 80, 120, 160, 200]) {
    const r = await get(
      `https://api.bilibili.com/x/v3/fav/resource/list?media_id=${DEFAULT_FOLDER}&pn=${pn}&ps=20&platform=web&order=mtime`,
      cookie,
    );
    const ms = r.j?.data?.medias || [];
    if (!ms.length) break;
    const dts = ms.map((m) => new Date((m.fav_time || 0) * 1000).toISOString().slice(0, 10)).sort();
    deepSamples.push({ pn, n: ms.length, from: dts[0], to: dts[dts.length - 1], titles: ms.map((m) => m.title || '') });
    console.log(`  深页 pn=${pn} → ${ms.length} 条，${dts[0]} ~ ${dts[dts.length - 1]}`);
    await sleep(400);
  }
}

// ---------- 增量筛选 ----------
const fresh = items.filter((x) => x.d && x.d > SINCE && !DEAD.test(x.t));
const deadNew = items.filter((x) => x.d && x.d > SINCE && DEAD.test(x.t));
console.log(`\n窗口内新增 ${fresh.length} 条（另有失效 ${deadNew.length} 条已剔除）`);

if (!fresh.length) {
  console.log('本次没有新数据，画像不变。');
  BASE.history.push({ at: TODAY, event: '增量更新', newItems: 0, note: `窗口 > ${SINCE}，无新增` });
  fs.writeFileSync(BASE_FILE, JSON.stringify(BASE, null, 2), 'utf8');
  process.exit(0);
}

const days = Math.max(1, Math.round(
  (new Date(items[0].d) - new Date(SINCE)) / 864e5,
));
const rate = (fresh.length / days).toFixed(1);
console.log(`日均 ${rate} 条/天（窗口 ${days} 天）`);

// ---------- 主题对比 ----------
const rows = [];
for (const [name, re] of TOPICS) {
  const n = fresh.filter((x) => re.test(x.t)).length;
  if (!n) continue;
  const baseN = BASE.topicCounts[name] || 0;
  const baseTotal = BASE.baselineSample.valid;
  const share = (n / fresh.length) * 100;
  const baseShare = baseN ? (baseN / baseTotal) * 100 : 0;
  rows.push({ name, n, share, baseN, baseShare, delta: share - baseShare });
}
rows.sort((a, b) => b.delta - a.delta);

const label = (r) => {
  const inBase = BASE.topicCounts[r.name] > 0;
  if (!inBase && r.n >= 2) return '新冒头';
  if (!inBase) return '零星';
  if (r.delta >= 1.5) return '升温';
  if (r.delta <= -1.5) return '冷却';
  return '持平';
};

console.log('\n主题'.padEnd(14), '新增', '本窗占比', '基线占比', '变化', '  形态');
for (const r of rows) {
  const d = r.delta >= 0 ? '+' + r.delta.toFixed(1) : r.delta.toFixed(1);
  console.log(
    r.name.padEnd(14),
    String(r.n).padStart(4),
    (r.share.toFixed(1) + '%').padStart(8),
    (r.baseShare.toFixed(1) + '%').padStart(8),
    d.padStart(7),
    '  ' + label(r),
  );
}
const vanished = Object.keys(BASE.topicCounts).filter(
  (k) => BASE.topicCounts[k] >= 5 && !rows.some((r) => r.name === k),
);
if (vanished.length) console.log('\n⚠️ 基线里有过、本窗口一条都没有：', vanished.join('、'));

const tagged = fresh.filter((x) => TOPICS.some(([, re]) => re.test(x.t))).length;
console.log(`\n归类率 ${(tagged / fresh.length * 100).toFixed(0)}%（基线 28%）`);
console.log(`不重复 UP ${new Set(fresh.map((x) => x.u).filter(Boolean)).size} 个`);

// ---------- 写报告 ----------
const L = [];
L.push(`# 画像增量 · ${TODAY}`, '');
L.push(`> 基线日 **${BASE.profileBaseline}** · 本次窗口 \`fav_time > ${SINCE}\``);
L.push(`> 新增 **${fresh.length}** 条 / ${days} 天（日均 ${rate}）· 剔除失效 ${deadNew.length} 条`);
L.push(`> 登录账号：${UNAME}（uid ${UID}）`, '');
L.push('## 主题变化', '');
L.push('| 主题 | 新增 | 本窗占比 | 基线占比 | 变化 | 形态 |');
L.push('|---|---:|---:|---:|---:|---|');
for (const r of rows) {
  const d = r.delta >= 0 ? '+' + r.delta.toFixed(1) : r.delta.toFixed(1);
  L.push(`| ${r.name} | ${r.n} | ${r.share.toFixed(1)}% | ${r.baseShare.toFixed(1)}% | ${d}pp | ${label(r)} |`);
}
L.push('');
if (vanished.length) L.push(`**⚠️ 基线里有过、本窗口一条都没有：** ${vanished.join('、')}`, '');
L.push(`归类率 ${(tagged / fresh.length * 100).toFixed(0)}%（基线 28%）· 不重复 UP ${new Set(fresh.map((x) => x.u).filter(Boolean)).size} 个`, '');

const emerging = rows.filter((r) => label(r) === '新冒头');
if (emerging.length) {
  L.push('## 新冒头的题材（脉冲候选）', '');
  for (const r of emerging) {
    const sample = fresh.filter((x) => TOPICS.find((t) => t[0] === r.name)[1].test(x.t)).slice(0, 5);
    L.push(`### ${r.name} —— ${r.n} 条`);
    sample.forEach((s) => L.push(`- ${s.d} · ${s.t.slice(0, 60)}`));
    L.push('');
  }
}

const cooling = rows.filter((r) => label(r) === '冷却');
if (cooling.length) {
  L.push('## 正在冷却', '');
  cooling.forEach((r) => L.push(`- **${r.name}**：${r.baseShare.toFixed(1)}% → ${r.share.toFixed(1)}%（${r.delta.toFixed(1)}pp）`));
  L.push('');
}

if (deepSamples.length) {
  L.push('## 深页抽样（长跨度判定）', '');
  L.push('| 页码 | 条数 | 收藏时间范围 |');
  L.push('|---|---:|---|');
  deepSamples.forEach((d) => L.push(`| pn=${d.pn} | ${d.n} | ${d.from} ~ ${d.to} |`));
  L.push('');
}

L.push('## 更新基线', '');
L.push('确认这次变化后，把 `BASELINE.json` 的 `topicCounts` / `topicSharePct` / `timeShape`');
L.push('按上面这张表重算一遍（或者告诉我，我来改）。', '');
L.push('---', '', '原始新增条目：', '', '```');
fresh.slice(0, 300).forEach((x) => L.push(`${x.d}\t${x.t.slice(0, 70)}\t${x.u}`));
L.push('```', '');

const outFile = path.join(HERE, `画像-增量-${TODAY}.md`);
fs.writeFileSync(outFile, L.join('\n'), 'utf8');
console.log('\n已写出 ' + outFile);

BASE.history.push({
  at: TODAY,
  event: '增量更新',
  newItems: fresh.length,
  days,
  perDay: Number(rate),
  report: path.basename(outFile),
  note: `窗口 > ${SINCE}`,
});
BASE.lastPull = TODAY;
fs.writeFileSync(BASE_FILE, JSON.stringify(BASE, null, 2), 'utf8');
console.log('BASELINE.json 已记录本次更新（基线日不变，仍是 ' + BASE.profileBaseline + '）');
