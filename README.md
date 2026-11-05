# dsh-bili-duty

让 AI **每天替你在 B站 刷一轮**：挑出值得看的、按播放量从高到低排、私信给你；
你看完回几个分数，它把口味**回流成搜索关键词**；回 `/命令` 还能把私信当控制台用。

这套东西是围绕 [DSH（DeepSeek Harness）](https://github.com/deepseek-ai) 的两个插件搭起来的**外围工具集**：

| 上游插件 | 作用 |
|---|---|
[dsh-bili-scroll](https://github.com/c1overzz/dsh-bili-scroll) | 定时起一个 headless 轮，读字幕/抽帧、挑视频、写日报、发私信 |
[dsh-video-storyboard](https://github.com/SAOS-3624/dsh-video-storyboard) | 从 B站 自带故事板裁帧，让模型"看见"画面 |

本仓库是**在它们之上加的那一层**：评价闭环、私信控制台、对账补记、账单统计。

---

## 它干了什么（三条链路）

```
                    ┌──────────────── 值班轮（插件负责）────────────────┐
  12:00 / 18:00 ──▶ │ 搜关键词(order=click) → 读字幕/抽帧 → 挑 6~12 条   │
                    │ → 写报告 out/<日期>.md → 私信发给你（≤4 批）      │
                    └───────────────────┬───────────────────────────────┘
                                        │ 你回：1=10 3=11 5=-1 4 调色真舒服
                    ┌───────────────────▼───────────────────────────────┐
  私信控制台(本仓库) │ 1 分 钟扫一次私信：                               │
  每 1 分钟         │   `/命令` → 执行并回你                            │
                    │   打分/评价 → 记账到 ratings.jsonl                │
                    │   其他话 → 起一个 headless 轮当"简化版对话"回你    │
                    └───────────────────┬───────────────────────────────┘
                                        │ 11 分提词 / -1 分删词 / 文字评价进缓冲区
                    ┌───────────────────▼───────────────────────────────┐
                    │ config.json 的 keywords + persona.md 的 RATINGS    │
                    │ ⇒ 下一轮就按新方向去找                             │
                    └───────────────────────────────────────────────────┘
```

### 1. 评价闭环（`评分.mjs`）

不是"打个 0-10 就完事"，而是分了四档：

| 你发 | 发生了什么 |
|---|---|
| `1=10 3=9` | 记账。只评几条也行，**不用每条都评** |
| `2=11 空岛那段取舍讲得清楚` | ★特别好：11 分，并从这句话里**提词加进搜索关键词** |
| `5=-1 标题党全程废话` | ✗特别差：-1 分，并把理由里点到的词**从关键词里删掉** |
| `4 调色板真舒服` | 纯文字：**先进缓冲区**，同一个词在 ≥2 条评价里反复出现才动关键词 |

几个刻意的设计：

- **提词靠标题，不靠分词器**：取「你说的理由」和「那条视频标题」的最长公共子串，再顺着标题补全
  —— 理由说"空岛"，标题是"仅一格方块的**空岛生存**？" ⇒ 提到 `空岛生存`。理由和标题没交集就**不乱加**。
- **文字评价不立刻改方向**：一句话不该带偏搜索；攒到 3 条或手动 `--learn` 才学一次，且只认**反复出现过**的词。
- **全角/半角等价**：中文输入法打出来的是 `3＝11`（全角等号）、`１＝１０`（全角数字），
  归一化时**只做等长映射**（不能用 `normalize('NFKC')`，那会把中文逗号 `，` 改成 `,`、篡改原话）。

### 2. 私信控制台（`私信控制台.py`）

小号（投递号）与你的大号互关，于是私信成了一条双向通道。每 1 分钟扫一次：

```
/debug           总览：关键词·台账·缓冲区·排除词·今天额度·路由
/kw [add|del 词]  看/改搜索关键词
/mute [词]        软黑名单（标题/UP/简介出现就跳过）
/unmute 词        放出来
/ban UP名         这个 UP 一律不推
/list            最近 8 条台账
/last            今天挑了哪些（带链接，并自动比对判重表）
/buf             缓冲区现状          /learn  立刻学一次
/status          额度与窗口          /cost   今天花多少
/help
```

不打 `/` 的就是聊天 —— 会起一个 headless 轮（带人格 + 能现场查 B站）回你一句。
纯文字评价会被识别为"评价"而不是"聊天"，**不会被回一句废话**。

### 3. 对账补记（`对账补记.mjs`）

判重表（`seen.md`）是流水账，日报（`out/<日期>.md`）是给人看的。两者会**对不上**：

> 实测某天判重表记了 20 条「挑了」，日报里只有 6 个 `### BV` 行 —— 中午那轮挑的 12 条**整批没进报告**。

而宿主是按报告里的 `###` 行数算"今天挑了几条"的 ⇒ 额度算多 ⇒ 重复投递。
这个脚本每分钟跑一次，用判重表给报告补账，幂等；补记时会**核对真实标题**，
BV 大小写对不上（见下）会挂一条 ⚠️ 而不是悄悄写错链接。

---

## 快速上手

```bash
# 1) 装上游插件（两个都要）
dsh plugin --profile web add dsh-bili-scroll
dsh plugin --profile web add dsh-video-storyboard

# 2) 扫码登录 B站（小号），凭证落在 ~/.dsh/bili-duty/bili_credential.json

# 3) 起一个最小权限的 profile：~/.dsh/profiles/bili-duty/cordis.patch.yml
#    （见本仓库 patches/ 里的示例）

# 4) 把 local.example.json 复制成 bili-profile/local.json，填你的 uid 和路径

# 5) 试一下
node bili-profile/评分.mjs --list
node bili-profile/对账补记.mjs
python bili-profile/私信控制台.py --simulate "/debug"
```

把私信控制台挂成每分钟一次的计划任务（Windows）：

```powershell
# 无窗口启动：wscript 跑一个 VBS，WshShell.Run(cmd, 0, True) 的 0 = 隐藏窗口
# 生成器：python bili-profile/写无窗口启动器.py
Register-ScheduledTask -TaskName 'DSH-BiliDuty' `
  -Action (New-ScheduledTaskAction -Execute 'C:\Windows\System32\wscript.exe' `
            -Argument '"<路径>\console-launch.vbs"') `
  -Trigger (New-ScheduledTaskTrigger -Once -At (Get-Date) `
            -RepetitionInterval (New-TimeSpan -Minutes 1))
```

---

## 目录

```
bili-profile/
  评分.mjs              评价闭环（收私信里的打分/11/-1/纯文字 → 台账 → 关键词 → 画像）
  打分.mjs              旧入口，转发到 评分.mjs
  对账补记.mjs          判重表 ↔ 日报 对账并补记
  刷视频账单.mjs        按轮统计 token 与花费（分峰谷、分路由）
  私信控制台.py         私信当命令行 + 简易对话 + 失败告警
  console-launch.example.vbs   无窗口启动器模板
  写无窗口启动器.py     生成上面那个 vbs 并重挂计划任务
  更新画像.mjs          从 B站 收藏夹重算用户画像
  深页抽样.mjs          收藏夹深页抽样（画像用）
  测评分.mjs / 测控制台.py     自测（22 项 / 20 项，不需要网络）
  演练缓冲学习.mjs      在临时沙箱里演练"缓冲区学习"，不碰真实数据
  dump-session.mjs      解 DSH 的 zstd 会话记录
  看工具结果.mjs / 看私信.mjs / 看私信会话.mjs   排查用的三个查看器
patches/
  cordis.patch.example.yml    bili-duty profile 的最小权限补丁示例
  duty-settings.example.yaml  值班轮专用 settings（单模型/单路由）
```

---

## 踩过的坑（这部分最有价值）

1. **BV 号大小写敏感，而且两种大小写都是真实视频**
   `BV1Ms411m7Pf`《东方原曲合集 793P》vs `BV1ms411m7Pf`《【兽人】I GOT YOU》—— 只差一个字母。
   模型手打一遍就会把用户送到别的视频。⇒ 发私信前做**链接体检**（真标题 vs 段落文字的相似度），
   同时对不上就拒发并告诉它链接实际是什么。

2. **`agent-default-model` 是「settings 用户层 > 组合配置」**
   只要 `~/.dsh/settings.yaml` 里有这一节，`--patch` overlay 里写的同一条**永远不生效**。
   想给值班轮单独指定模型，得在 **profile 层**把 `settings` 的 `config.path` 指到另一份文件。

3. **uv 建的 venv 里 `pythonw.exe` 不是无窗口版**
   实测 PE header `subsystem = 3`（控制台）—— 跟 `python.exe` 一样。用它当计划任务动作照样弹黑框。
   ⇒ `wscript` + `WshShell.Run(..., 0, True)` 才对任何控制台程序都有效。
   另外 pythonw 下 `sys.stdout` 是 `None`，`print()` 会直接崩。

4. **日报会被回滚，且诊断了三次都不是我以为的地方**
   `duty_report_append` 是纯追加（`open(mode="a")`），宿主侧的占位报告也有存在性检查。
   最终没找到根因，但用「每分钟对账补记」把后果止血了 —— 有时候工程上的答案是"让错误无害"，不是"消灭错误"。

5. **`.gitignore` 的行尾 `#` 注释不是注释**
   `local.json     # 本地配置` 会被当成一条规则 `local.json     # 本地配置`，**永远匹配不上**。
   差点把 uid 和个人画像提交上去。

6. **1 分钟一次的扫描要跨进程互斥**
   新一轮可能在上轮还没跑完时启动，同一条命令会被回两次。用 `O_EXCL` 建锁文件；
   判"值班轮在不在跑"只看 `run-lock.json` 里的 `pid`，**不能看文件新旧**（跑完那一刻文件也是刚写过的）。

---

## 隐私

仓库里**只有代码和文档**。以下内容一律 `.gitignore`：
个人画像、B站 uid、收藏夹抓取数据、私信记录、日记/判重表、本机绝对路径（`local.json`）。
脚本按 **环境变量 > `local.json` > 默认值** 取值，换机器只用填一个 `local.json`。

B站 凭证（`bili_credential.json` 里的 SESSDATA）**等同于你的登录态**，任何情况下都不要提交。

## License

MIT。上游两个插件的版权归各自作者（见 `dsh-bili-scroll/LICENSE`、`dsh-video-storyboard/LICENSE`）。
