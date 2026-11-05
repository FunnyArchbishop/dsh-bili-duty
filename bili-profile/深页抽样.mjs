#!/usr/bin/env node
/**
 * 深页抽样.mjs —— 一次性回填：补齐默认收藏夹里「更老的 3800+ 条」那一块空白
 *
 * 目的：验证「稳态」这四个兴趣到底跨了多久 —— 是三个月还是三年。
 * 做法：在全 228 页里均匀抽样 ~38 页（约 760 条），得到一条贯穿整个收藏史的时间轴。
 *
 * 用法：
 *   node 深页抽样.mjs
 *   node 深页抽样.mjs --step 4      # 更密（页距 4，约 1140 条）
 *   node 深页抽样.mjs --uid <你的uid>
 *
 * 输出：终端摘要 + 画像-长跨度分析.md + raw-深页抽样.tsv
 * 只读网、只写本目录。凭证全程留在进程内存，不落盘。
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
const HDR = { 'user-agent': UA, referer: 'https://www.bilibili.com/' };
const FOLDER = 827971601;
const TODAY = new Date().toISOString().slice(0, 10);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const argv = process.argv.slice(2);
const pickArg = (k) => { const i = argv.indexOf(k); return i >= 0 ? argv[i + 1] : null; };
const STEP = Math.max(1, Number(pickArg('--step') || 6));
const WANT_UID = Number(pickArg('--uid') || 0);

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
  ['番剧/动画', /番剧|新番|动画|剧场版|解说|二创|mmd/],
  ['王者/LOL', /王者荣耀|英雄联盟|\blol\b|柯洁|围棋|cs2|无畏契约|瓦罗兰特/],
  ["Terraria模组", /灾厄|模组|mod\b|开荒|建筑|建家/],
];
const DEAD = /已失效|失效视频/;

async function get(url, cookie) {
  const h = { ...HDR };
  if (cookie) h.cookie = cookie;
  const r = await fetch(url, { headers: h });
  const t = await r.text();
  let j = null;
  try { j = JSON.parse(t); } catch { /* not json */ }
  return { j, r, t };
}

async function login() {
  let buvid = '';
  try {
    const o = await get('https://api.bilibili.com/x/frontend/finger/spi');
    if (o.j?.data) buvid = `buvid3=${o.j.data.b_3}; buvid4=${o.j.data.b_4}`;
  } catch { /* ignore */ }

  // 二维码会过期（实测 86038 出现得比预期早）——过期就自动换一张，不中断
  for (let attempt = 1; attempt <= 6; attempt++) {
    const gen = await get('https://passport.bilibili.com/x/passport-login/web/qrcode/generate');
    if (!gen.j?.data) { console.log('GEN_FAIL'); process.exit(2); }
    const key = gen.j.data.qrcode_key;
    console.log(`\n=== 第 ${attempt}/6 张码 —— 请用手机 B站 App 扫（大号）===`);
    console.log('SCAN_URL ' + gen.j.data.url);
    console.log('WAITING...（这张过期会自动换下一张，不用重跑脚本）');

    const t0 = Date.now();
    let next = false;
    while (Date.now() - t0 < 4 * 60 * 1000) {
      await sleep(2200);
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
        console.log('SCANNED_OK');
        return ck;
      }
      if (code === 86038) { console.log('QR_EXPIRED —— 换下一张'); next = true; break; }
      if (code === 86090) { console.log('（已扫码，等待手机上点确认…）'); }
    }
    if (!next) console.log('TIMEOUT —— 这张等超时了，换下一张');
  }
  console.log('NO_COOKIE 六张码都没扫成');
  process.exit(4);
}

const cookie = await login();
const nav = await get('https://api.bilibili.com/x/web-interface/nav', cookie);
if (!nav.j?.data?.mid) { console.log('NAV_FAIL ' + JSON.stringify(nav.j).slice(0, 300)); process.exit(5); }
const UID = nav.j.data.mid;
console.log(`LOGIN_OK ${nav.j.data.uname} uid=${UID}`);
if (WANT_UID && UID !== WANT_UID) { console.log(`⚠️ uid=${UID} ≠ 期望 ${WANT_UID}，中止`); process.exit(6); }

// 先拿总数
const one = await get(`https://api.bilibili.com/x/v3/fav/resource/list?media_id=${FOLDER}&pn=1&ps=20&platform=web&order=mtime`, cookie);
const info = one.j?.data?.info || {};
const TOTAL = Number(info.media_count || 0);
const PAGES = Math.ceil(TOTAL / 20) || 1;
console.log(`收藏夹「${info.title || '?'}」共 ${TOTAL} 条 → ${PAGES} 页，页距 ${STEP}，预计抽样 ${Math.ceil(PAGES / STEP)} 页`);

// 均匀抽样
const targets = [];
for (let pn = 1; pn <= PAGES; pn += STEP) targets.push(pn);
if (targets[targets.length - 1] !== PAGES) targets.push(PAGES);

const rows = [];
const print = [];
for (const pn of targets) {
  const r = await get(`https://api.bilibili.com/x/v3/fav/resource/list?media_id=${FOLDER}&pn=${pn}&ps=20&platform=web&order=mtime`, cookie);
  const ms = r.j?.data?.medias || [];
  if (!ms.length) { print.push([pn, 0, '-', '-']); continue; }
  const ds = ms.map((m) => new Date((m.fav_time || 0) * 1000).toISOString().slice(0, 10)).sort();
  for (const m of ms) {
    const d = new Date((m.fav_time || 0) * 1000).toISOString().slice(0, 10);
    rows.push({ pn, d, t: (m.title || '').replace(/[\t\n\r]/g, ' '), u: m.upper?.name || '', b: m.bvid || '' });
  }
  print.push([pn, ms.length, ds[0], ds[ds.length - 1]]);
  await sleep(380);
}

const valid = rows.filter((x) => !DEAD.test(x.t));
const dead = rows.filter((x) => DEAD.test(x.t));
const allDates = valid.map((x) => x.d).sort();
const D0 = allDates[0];
const D1 = allDates[allDates.length - 1];
const spanDays = Math.round((new Date(D1) - new Date(D0)) / 864e5);

console.log(`\n抽样页数 ${print.length}，拿到 ${rows.length} 条，有效 ${valid.length}，失效 ${dead.length}`);
console.log(`抽样覆盖时间：${D0} ~ ${D1}（跨度 ${spanDays} 天 ≈ ${(spanDays / 30.4).toFixed(1)} 个月）`);

// 按月分布（抽样口径）
const byMonth = {};
valid.forEach((x) => { const m = x.d.slice(0, 7); byMonth[m] = (byMonth[m] || 0) + 1; });
const months = Object.keys(byMonth).sort();
console.log('\n== 抽样：按月（每月抽样命中数，非全量） ==');
months.forEach((m) => {
  console.log(' ', m, String(byMonth[m]).padStart(3), '▇'.repeat(Math.min(50, byMonth[m])));
});

// 分桶：把整个时间轴切成 6 段，看每个主题在几段里出现
const BUCKETS = 6;
const t0n = new Date(D0).getTime();
const t1n = new Date(D1).getTime();
const bucketOf = (d) => Math.min(BUCKETS - 1, Math.floor((new Date(d).getTime() - t0n) / Math.max(1, (t1n - t0n) / BUCKETS)));
const bucketLabels = [];
for (let i = 0; i < BUCKETS; i++) {
  const a = new Date(t0n + ((t1n - t0n) / BUCKETS) * i).toISOString().slice(0, 7);
  const b = new Date(t0n + ((t1n - t0n) / BUCKETS) * (i + 1)).toISOString().slice(0, 7);
  bucketLabels.push(a + '~' + b);
}

const res = [];
for (const [name, re] of TOPICS) {
  const hit = valid.filter((x) => re.test(x.t));
  if (hit.length < 3) continue;
  const ds = hit.map((x) => x.d).sort();
  const first = ds[0];
  const last = ds[ds.length - 1];
  const span = Math.round((new Date(last) - new Date(first)) / 864e5);
  const buckets = new Set(hit.map((x) => bucketOf(x.d)));
  const coverage = buckets.size / BUCKETS;
  const months_ = new Set(hit.map((x) => x.d.slice(0, 7))).size;
  let verdict;
  if (span >= 180 && coverage >= 0.6) verdict = '长跨度稳态';
  else if (span >= 180) verdict = '长跨度间歇';
  else if (span >= 90) verdict = '中期';
  else if (new Date(last) < new Date(new Date(D1).getTime() - 60 * 864e5)) verdict = '已消退';
  else verdict = '近期起势';
  res.push({ name, n: hit.length, first, last, span, coverage, months: months_, verdict, heat: Array.from({ length: BUCKETS }, (_, i) => (buckets.has(i) ? '█' : '·')).join('') });
}
res.sort((a, b) => b.span - a.span || b.n - a.n);

console.log('\n主题'.padEnd(14), '命中', '首~末'.padStart(21), '跨度', '分段覆盖', '  6段热力', '   判定');
for (const r of res) {
  console.log(
    r.name.padEnd(14),
    String(r.n).padStart(4),
    (r.first + ' ~ ' + r.last).padStart(21),
    (r.span + '天').padStart(6),
    (r.heat + ' ' + (r.coverage * 100).toFixed(0) + '%').padStart(9),
    '  ' + r.verdict,
  );
}
console.log('\n分段边界：');
bucketLabels.forEach((b, i) => console.log(`  段${i}: ${b}`));

// ---------- 落盘 ----------
fs.writeFileSync(
  path.join(HERE, 'raw-深页抽样.tsv'),
  ['pn\tfav_time\ttitle\tupper\tbvid', ...rows.map((x) => `${x.pn}\t${x.d}\t${x.t}\t${x.u}\t${x.b}`)].join('\n'),
  'utf8',
);

const L = [];
L.push(`# 长跨度分析（深页抽样）· ${TODAY}`, '');
L.push('> 目的：验证「稳态」兴趣到底跨了多久 —— 三个月还是三年。');
L.push(`> 做法：默认收藏夹共 ${TOTAL} 条 / ${PAGES} 页，按页距 ${STEP} 均匀抽样 ${print.length} 页，`);
L.push(`> 得 ${rows.length} 条，有效 ${valid.length} 条（剔除失效 ${dead.length} 条）。`);
L.push(`> 抽样覆盖 **${D0} ~ ${D1}，跨度 ${spanDays} 天 ≈ ${(spanDays / 30.4).toFixed(1)} 个月**`, '');
L.push('## 抽样命中的时间轴（按月，抽样口径，非全量）', '');
L.push('```');
months.forEach((m) => L.push(`${m}  ${String(byMonth[m]).padStart(3)}  ${'▇'.repeat(Math.min(60, byMonth[m]))}`));
L.push('```', '');
L.push(`整条时间轴切成 ${BUCKETS} 段：`, '');
bucketLabels.forEach((b, i) => L.push(`- 段${i}：${b}`));
L.push('');
L.push('## 主题长跨度表', '');
L.push('| 主题 | 命中 | 首次 | 最近 | 跨度 | 覆盖段 | 热力 | 判定 |');
L.push('|---|---:|---|---|---:|---|---:|---|');
for (const r of res) {
  L.push(`| ${r.name} | ${r.n} | ${r.first} | ${r.last} | ${r.span}天 | ${(r.coverage * 100).toFixed(0)}% | \`${r.heat}\` | ${r.verdict} |`);
}
L.push('');
L.push('## 判定标准', '');
L.push('- **长跨度稳态**：跨度 ≥180 天 且 覆盖 ≥60% 的分段 → 真·长期品味');
L.push('- **长跨度间歇**：跨度 ≥180 天 但覆盖 <60% → 一直存在但断续（季节性/周期性）');
L.push('- **中期**：跨度 90~180 天');
L.push('- **已消退**：最近一次早于抽样截止前 60 天');
L.push('- **近期起势**：跨度 <90 天且最近仍在出现');
L.push('');
L.push('## 抽样页明细', '');
L.push('| 页码 | 条数 | 该页时间范围 |');
L.push('|---|---:|---|');
print.forEach(([pn, n, a, b]) => L.push(`| pn=${pn} | ${n} | ${a} ~ ${b} |`));
L.push('');
L.push('---', '', '原始数据：`raw-深页抽样.tsv`', '');

const outFile = path.join(HERE, '画像-长跨度分析.md');
fs.writeFileSync(outFile, L.join('\n'), 'utf8');
console.log('\n已写出 ' + outFile);
console.log('已写出 ' + path.join(HERE, 'raw-深页抽样.tsv'));
