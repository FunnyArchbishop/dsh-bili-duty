#!/usr/bin/env node
/**
 * 打分.mjs —— 已退役，全部逻辑搬到了 `评分.mjs`
 * （新版支持：0~10 打分 / **11 分**（特别好评，会提词加进搜索关键词）/ **-1 分**（特别差，会删词）/
 *   只写一句文字评价 / 不必每条都评。）
 *
 * 这个文件只做转发，旧命令照样能用：
 *   node 打分.mjs              → node 评分.mjs
 *   node 打分.mjs --dry        → node 评分.mjs --dry
 *   node 打分.mjs --list       → node 评分.mjs --list
 *   node 打分.mjs --report     → node 评分.mjs --report
 *   node 打分.mjs --set 3 10   → node 评分.mjs --set 3 10
 *
 * 老版本留了个备份：打分.mjs.old
 */
import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const target = path.join(here, '评分.mjs')
const r = spawnSync(process.execPath, [target, ...process.argv.slice(2)], { stdio: 'inherit' })
process.exitCode = r.status ?? 0
