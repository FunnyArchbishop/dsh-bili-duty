# dsh-bili-duty

让 AI **每天替你在 B站 刷一轮**：按播放量挑出值得看的、私信给你；你看完回几个分数，
它把口味**回流成搜索关键词**；回 `/命令` 还能把私信当控制台用。

这是围绕 [DSH（DeepSeek Harness）](https://github.com/deepseek-ai) 两个插件搭的**外围工具集**。
上游插件不在本仓库（各自是独立仓库）：

| 上游插件 | 作用 |
|---|---|
[dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll) | 定时起一个 headless 轮：读字幕/抽帧、挑视频、写日报、发私信 |
[dsh-video-storyboard](https://github.com/SAOS-3624/dsh-video-storyboard) | 从 B站 自带故事板裁帧，让模型"看见"画面 |

---

## 三条链路

```
                ┌──────────── 值班轮（插件负责）────────────┐
 12:00 / 18:00 ▶│ 搜关键词(order=click) → 读字幕/抽帧      │
                │ → 挑 6~12 条 → 写日报 → 私信给你（≤4 批） │
                └──────────────────┬───────────────────────┘
                                   │ 你回：1=10 3=11 5=-1 4 调色真舒服
                ┌──────────────────▼───────────────────────┐
 私信控制台     │ 每 1 分钟扫一次私信：                     │
 （本仓库）     │  /命令 → 执行并回你                       │
                │  打分 / 评价 → 记账                       │
                │  其他话 → 起一轮当"简化版对话"回你        │
                └──────────────────┬───────────────────────┘
                                   │ 11 提词 / -1 删词 / 文字评价进缓冲区
                ┌──────────────────▼───────────────────────┐
                │ keywords + persona 的 RATINGS ⇒ 下一轮按新方向找 │
                └──────────────────────────────────────────┘
```

### 1. 评价闭环 `评分.mjs`

| 你发 | 发生了什么 |
|---|---|
| `1=10 3=9` | 记账。**不用每条都评** |
| `2=11 空岛那段取舍讲得清楚` | ★特别好：11 分，并从这句话里**提词加进关键词** |
| `5=-1 标题党全程废话` | ✗特别差：-1 分，并把理由里点到的词**从关键词删掉** |
| `4 调色板真舒服` | 纯文字：**先进缓冲区**，同一个词在 ≥2 条评价里出现才动关键词 |

- **提词靠标题、不靠分词器**：取「你说的理由」和「视频标题」的最长公共子串，再顺着标题补全（理由说"空岛"、标题是"仅一格方块的**空岛生存**？" ⇒ `空岛生存`）。没交集就不加。
- **提不出词就追问，不静默失败**：`3=11 有深度` 这种（"有深度"不在标题里）会私信回你一组选项 ——
  `【怎么好】1 有考据 2 讲得清楚 3 选题妙 4 制作精良` / `【加哪个词】5 儿童漫画 6 艺术家`，
  回 `1 5` 就行，也可以直接说一句。判据进统计，选中的词进关键词。同时只挂一个，24 小时不回就丢。
  > 打分的解析优先级高于追问：`1=10 3=9` 永远不会被当成"回答"吞掉。
- **文字评价不立刻改方向**：攒到 3 条或 `--learn` 才学一次，且只认反复出现过的词。

### 2. 私信控制台 `私信控制台.py`

小号与大号互关，私信成了双向通道。每 1 分钟扫一次：

```
/debug   总览（关键词·台账·缓冲区·排除词·额度·路由）
/kw      看关键词 ｜ /kw add 词 ｜ /kw del 词
/mute    软黑名单 ｜ /mute 词 ｜ /unmute 词 ｜ /ban UP名
/list    最近台账        /last   今天挑了哪些（自动比对判重表）
/buf     缓冲区          /learn  立刻学一次
/status  额度与窗口      /cost   今天花多少        /help
```

不打 `/` 的就是聊天：起一个 headless 轮（带人格、能现场查 B站）回一句。
纯文字评价会被识别成"评价"而不是"聊天"，不会回一句废话。

### 3. 对账补记 `对账补记.mjs`

判重表是流水账，日报是给人看的，两者会**对不上**。实测某天判重表记了 20 条「挑了」、
日报里只有 6 个 `### BV` 行 —— 中午那轮挑的 12 条整批没进报告。而宿主是按报告里的 `###`
行数算"今天挑了几条"的 ⇒ 额度算多 ⇒ 重复投递。这个脚本每分钟跑一次，用判重表补账、幂等，
补记时还会核对真实标题。

---

## 快速上手

```bash
dsh plugin --profile web add dsh-bili-scroll
dsh plugin --profile web add dsh-video-storyboard
python patches/应用补丁.py            # ← 给插件的 mcp_server.py 打上我们的两道闸
# 扫码登录 B站（小号），凭证落在 ~/.dsh/bili-duty/bili_credential.json
# profile 补丁由上面的脚本铺到 ~/.dsh/profiles/bili-duty/cordis.patch.yml
cp bili-profile/local.example.json bili-profile/local.json   # 填 uid 和路径

node bili-profile/评分.mjs --list
node bili-profile/对账补记.mjs
python bili-profile/私信控制台.py --simulate "/debug"
```

挂成每分钟一次的计划任务（Windows，无窗口）：

```powershell
python bili-profile/写无窗口启动器.py     # 生成 console-launch.vbs
Register-ScheduledTask -TaskName 'DSH-BiliDuty' `
  -Action (New-ScheduledTaskAction -Execute 'C:\Windows\System32\wscript.exe' `
            -Argument '"<路径>\console-launch.vbs"') `
  -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 1))
```

## 目录

| | |
|---|---|
`评分.mjs` / `打分.mjs` | 评价闭环（旧入口转发到新的） |
`对账补记.mjs` | 判重表给日报补账 |
`刷视频账单.mjs` | 按轮统计 token 与花费（分峰谷、分路由） |
`私信控制台.py` | 私信当命令行 + 简易对话 + 失败告警 |
`写无窗口启动器.py` + `.example.vbs` | 生成无窗口启动器 |
`更新画像.mjs` / `深页抽样.mjs` | 从收藏夹重算用户画像 |
`测评分.mjs` / `测控制台.py` | 自测（22 项 / 20 项，不联网） |
`演练缓冲学习.mjs` | 在临时沙箱里演练缓冲区学习 |
`dump-session.mjs` / `看工具结果.mjs` / `看私信*.mjs` | 排查用查看器 |

### 对上游的补丁（`patches/`）

上游插件只改**两个文件**（共 219 行），所以不整体 fork，做成可重放的补丁：

| | |
|---|---|
`patches/mcp_server/patched.py` | 我们维护的版本，**改这里就等于改补丁** |
`patches/mcp_server/mcp_server.patch` | 与上游基线的 unified diff（+211 / −1 行） |
`patches/index_js/index_js.patch` | 同上（+8 / −2 行）—— 修「日报被砍、额度算少」 |
`patches/应用补丁.py` | `--check` / 应用 / `--revert`，比 sha256 判断"可应用 / 已应用 / 上游变了" |
`patches/生成补丁集.py` | 上游升级后重跑，刷新 diff 与指纹 |
`patches/cordis.patch.yml` | 值班轮最小权限 profile |

改的三块：`bili_search` 的按播放量搜法说明 + 发私信前的**两道闸**（链接体检 / 投递闸门）
+ **召回工具放行**（`bili_rank` / `bili_hot_videos` / `bili_weekly_hot` 不受白名单限制）。
详见 `patches/README.md`。

> **为什么需要放行榜单工具**：只靠 `order="click"`（全时段播放量排序）会让候选永远落在
> 历史头部，反复端上同一批、候选池迅速枯竭。B站 的 `bili_rank(category, day=3|7)` 是
> **官方"近期热度"榜**（内容质量 + 近期数据动态排），正好替代它；配合
> `bili_weekly_hot` 和 `bili_search(order="pubdate")` 做新片探测，再用
> **「日均播放 = 播放量 ÷ 发布天数」**排序，就把"太老"和"太新没人看"两个毛病一起治了。

---

## License

MIT。上游两个插件的版权归各自作者。

---

<details>
<summary>踩坑记录（点开）</summary>

| # | 踩的坑 | 正确做法 |
|---|---|---|
1 | **BV 号大小写敏感**：`BV1Ms411m7Pf`（东方原曲合集 793P）和 `BV1ms411m7Pf`（【兽人】I GOT YOU）是两个不同的真实视频 | 发私信前做链接体检：真标题 vs 段落文字相似度，对不上就拒发并回报真实标题 |
2 | **`agent-default-model` 是「settings 用户层 > 组合配置」** | 只要 `settings.yaml` 里有这节，`--patch` overlay 的同一条永远不生效；要单独指定模型得在 profile 层改 `settings` 的 `config.path` |
3 | **uv 建的 venv 里 `pythonw.exe` 不是无窗口版**（PE `subsystem=3`） | 用 `wscript` + `WshShell.Run(cmd, 0, True)`；另注意 pythonw 下 `sys.stdout` 是 `None`，`print()` 会崩 |
4 | **日报会被回滚**，排查三处都不是根因 | 没找到根因，改用"每分钟对账补记"把后果变成无害 |
5 | **`.gitignore` 行尾的 `#` 不是注释**：`local.json  # 说明` 会变成一条永远匹配不上的规则 | 规则独占一行（差点把 uid 和画像提交上去） |
6 | **1 分钟扫描要跨进程互斥** | `O_EXCL` 锁文件；判"值班轮在不在跑"只看 `run-lock.json` 的 `pid`，不能看文件新旧（跑完那刻文件也是刚写的） |

</details>
