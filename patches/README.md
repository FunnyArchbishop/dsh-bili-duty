# patches/ —— 我们对上游做的补丁

## 为什么是"补丁"而不是 fork

上游 [`dsh-bili-scroll`](https://github.com/c1overzz/dsh-bili-scroll) 是个人维护的插件。
我们只改**两个文件、总共 219 行**，所以不整体搬进仓库（那会失去上游更新、且每次升级都要对一遍冲突），
而是把改动做成可重放的补丁：**装上游 + 跑一次脚本 = 和我们一模一样的环境**。

```
patches/
  mcp_server/
    base-2.3.1.py     上游原样（基线）
    patched.py        我们维护的版本  ← 「也能改」就是改这个
    mcp_server.patch  两者的 unified diff（+211 / −1）
    SHA256.txt        指纹
  index_js/
    base-2.3.1.js
    patched.js
    index_js.patch    （+8 / −2，就 21 行）
    SHA256.txt
  应用补丁.py          铺到目标位置，按 sha256 判断状态
  生成补丁集.py        上游升级后重跑，刷新 diff 与指纹
  cordis.patch.yml     值班轮的最小权限 profile
  duty-settings.example.yaml  值班轮专用 settings（单模型/单路由）
```

## 改了什么

### ① `vendor/bilibili-mcp/mcp_server.py` —— +211 / −1

1. **`bili_search` 的用法说明**：明确要求按 `order="click"`（播放量）搜、先看 `play`/`pubdate`
   再决定细看谁、时间窗放宽到近 30 天。
2. **发私信前的两道闸**（`bili_send_message`）：
   - **链接体检**：BV 号**大小写敏感**，`BV1Ms411m7Pf`（东方原曲合集）和 `BV1ms411m7Pf`
     （【兽人】I GOT YOU）是两个不同的真实视频。拿真标题和私信里那段文字比相似度，对不上就拒发。
   - **投递闸门**：屏蔽词 / 屏蔽 UP / 时长上限 / 播放量下限。数据全来自同一个 `view` 接口，
     **零额外请求成本**。
3. **召回工具不受白名单限制**（`_ALWAYS`）：
   值班轮以前只能看到 `bili_search` / `bili_recommend`，候选永远落在"搜索那几百条 + 全时段播放量"，
   反复端上历史头部、候选池枯竭。现在 `bili_rank` / `bili_hot_videos` / `bili_weekly_hot` /
   `bili_video_zones` 无论白名单怎么写都放行 —— 都是**只读榜单接口**，安全。
   > `bili_reply`（发评论）**仍然被白名单挡着**，该挡的没漏。

> 这个文件是**每轮开跑时新读**的 ⇒ 改完不用重启 DSH。

### ② `index.js` —— +8 / −2

`writeRoundNotesToReport()` 里那两行：以前用 `indexOf('## 投递')` 找**第一个**投递段，
然后把它之后的全部内容砍掉；现在用 `lastIndexOf`，而且**只有当最后那个投递段后面没有别的
`###` 条目时才替换**，否则宁可多一段投递记录也绝不删任何已有内容。

**为什么非改不可**：这个函数每轮收尾都跑。日报是顺序追加的，所以只要某一轮写过 `## 投递`，
后面每一轮追加的 `### BV` 条目都会在**下一轮收尾时被吃掉**。实测后果：

| 现象 | 实测数据 |
|---|---|
日报每天只留得住**第一轮** | 11-05 判重表记了 20 条，报告只剩 6 个 `###` |
额度一直被算少 | 宿主按报告里的 `###` 行数算「今天挑了几条」 |
「补记」总消失 | 对账补记追加在末尾，正好落在杀伤区，反复被砍 |

> ⚠️ **这个文件要重启 DSH 才生效**（插件是宿主进程加载的）。重启前靠 `对账补记.mjs`
> 顶住 —— 它已经改成**插在第一个 `## 投递` 之前**（那块区域宿主动不到）。

## 怎么用

```bash
python patches/应用补丁.py --check    # 只看状态
python patches/应用补丁.py            # 应用（幂等，可重复跑）
python patches/应用补丁.py --revert   # 用 .orig-* 备份还原
```

`mcp_server.py` 会铺到**两个位置**（插件包里的 + `~/.dsh/bili-duty/` 家目录那份）——
插件启动时 `ensureHomeFiles` 会拿包里那份覆盖家目录，只有两份字节相同才会跳过。
`index.js` 只有插件包那一份。

### 顺手生成的「无黑框启动器」

跑应用脚本时还会用 `launcher/启动控制台.vbs.tpl` 生成 `bili-profile/启动控制台.vbs`
（桌面快捷方式指 `wscript.exe "…\启动控制台.vbs"`）。

为什么必须绕这一道：**这个 uv 造的 venv 里 `python.exe` 和 `pythonw.exe` 是同一份复制**
（都是 `subsystem=3` console，各 45568 字节），所以"换成 pythonw"根本不解决问题 —— 实测过。
只有 `WshShell.Run(cmd, 0, …)`（window style 0）才真不给窗口。模板生成时写成
**UTF-16 LE + BOM**，否则 `wscript` 按 ANSI 读 UTF-8 会把中文路径读坏。

## 状态判断

应用脚本不比 patch 上下文，而是比 **sha256**：

| 目标文件指纹 | 判定 | 动作 |
|---|---|---|
`== base` | 可应用 | 备份 `.orig-<时间戳>` 后覆盖 |
`== patched` | 已应用 | 跳过（幂等） |
其它 | **上游变了 / 被人改过** | **拒绝动手**，让你对照 `.patch` 手工合并 |

## 上游升级了怎么办

1. 新版本装好后，`python patches/应用补丁.py --check` 会报 `⚠️ 上游变了/被改过`
2. 从新版本里取出对应文件，存成 `base-<新版本>.<ext>`
3. 把 `patched.*` 里的改动手工合并进去（一共就 219 行，两个互不相干的区域）
4. 重跑 `生成补丁集.py` 刷新 `.patch` 和 `SHA256.txt`

## 为什么不用 `git apply` 作为应用方式

补丁要打到 `node_modules/` 里，那不是 git 仓库，`git apply` 会报
`fatal: this operation must be run in a work tree`。而按指纹整文件铺等价、更可控。

> 两个 `.patch` 依旧是**真补丁**——在临时 git 仓里 `git apply` 后指纹和 `patched.*`
> 完全一致，每次生成时都会验证。

## 两个坑（写补丁时踩的）

1. **`.patch` 必须以 LF 写入**：Windows 上 Python 的 `write_text` 默认把 `\n` 翻成 `\r\n`，
   而它描述的文件是 LF ⇒ 行尾对不上，`git apply` 全部失败。
2. **改 `index.js` 也要用二进制方式写回**：我用 `write_text` 改完，整个文件变成 CRLF，
   补丁从 8 行暴涨到 `+3079/-3073`（等于整篇重写），上游一升级就没法合并了。
   ⇒ 改 JS 文件时先 `read_bytes()` / 用完 `write_bytes()`，或者显式 `newline="\n"`。

## 顺带一个测试

`bili-profile/测报告不被砍.mjs` —— 它把装好的 `index.js` 里那段真实代码**抠出来**、
配上假 fs 跑，验证：

- 第 2 轮之后 6 条条目一条不少
- 文末投递段被替换（而不是越堆越多）
- 文件不存在时会建、`reportLevel=off` 时不动

**同一套测试跑在未打补丁的基线上会挂 2 条** —— 这就是 bug 的复现，也是补丁有效的证据。
