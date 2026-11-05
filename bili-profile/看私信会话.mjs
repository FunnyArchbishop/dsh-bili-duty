// 用 lib/dm.mjs 的真实字段（ts / fromMe / text）打印私信会话，并挑出「大号发来的打分」
import { readFileSync } from 'node:fs'
import { dirname } from 'node:path'
const HERE = dirname(process.argv[1] || '.')
const LOCAL = (() => { try { return JSON.parse(readFileSync(HERE + '/local.json', 'utf8')) } catch { return {} } })()
// dm.mjs 来自插件 dsh-bili-scroll。默认按 ~/.dsh/profiles/web/... 找，
// 装到别处就用环境变量 BILI_DM_LIB 指过去（形如 file:///.../lib/dm.mjs）。
import { pathToFileURL } from 'node:url'
const HOME_DIR = process.env.USERPROFILE || process.env.HOME || ''
const DM_LIB = process.env.BILI_DM_LIB || LOCAL.dmLib
  || pathToFileURL(HOME_DIR + '/.dsh/profiles/web/node_modules/dsh-bili-scroll/lib/dm.mjs').href
const { loadCred, fetchMsgs, myUid } = await import(DM_LIB)

const OWNER = Number(process.env.BILI_OWNER_UID || LOCAL.ownerUid || 0)
const stateDir = process.env.BILI_DUTY_HOME || LOCAL.dutyHome || ''
const cred = loadCred(stateDir)
const me = myUid(cred)
const msgs = await fetchMsgs(cred, OWNER, 50)

const bj = (ts) => (ts ? new Date(ts * 1000 + 8 * 3600e3).toISOString().slice(5, 16).replace('T', ' ') : '??-?? ????')
const RATING = /\b\d{1,2}\s*=\s*\d{1,2}\b/

console.log(`小号 ${me} ↔ 大号 ${OWNER}　共 ${msgs.length} 条（旧→新）\n`)
console.log('=== 最近 12 条 ===')
for (const m of msgs.slice(-12)) {
  const who = m.fromMe ? '小号→' : '大号→'
  console.log(`${bj(m.ts)} ${who} ${m.text.replace(/\n/g, ' ⏎ ').slice(0, 130)}`)
}

const ratings = msgs.filter((m) => !m.fromMe && RATING.test(m.text))
console.log(`\n=== 大号发来的打分：${ratings.length} 条 ===`)
for (const m of ratings) console.log(`  ${bj(m.ts)}  ${m.text.trim().slice(0, 120)}`)

const lastRating = ratings[ratings.length - 1]
const lastMine = [...msgs].reverse().find((m) => m.fromMe)
console.log('\n最后一次打分：', lastRating ? bj(lastRating.ts) : '（没有）')
console.log('最后一条小号发出：', lastMine ? bj(lastMine.ts) : '（没有）')
if (lastRating && lastMine) {
  console.log(lastRating.ts > lastMine.ts ? '⇒ 打分在那批之后，有回复' : '⇒ 这条打分是在更早的批次之后，今天这批还没打分')
}
