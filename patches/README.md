# patches/ —— 我们对上游做的补丁

## 为什么是"补丁"而不是 fork

上游 [`dsh-bili-scroll`](https://github.com/c1overzz/dsh-bili-scroll) 是个人维护的插件。
我们实际只改**一个文件**，所以不整体搬进仓库（那会失去上游更新、且每次升级都要对一遍冲突），
而是把改动做成可重放的补丁：**装上游 + 跑一次脚本 = 和我们一模一样的环境**。

```
patches/
  mcp_server/
    base-2.3.1.py      上游 2.3.1 的原文（基线，未改动）
    patched.py         我们维护的版本  ← 「也能改」就是改这个
    mcp_server.patch   两者的 unified diff（审阅 / 上游升级时手工合并用）
    SHA256.txt         两个版本的指纹，应用脚本靠它判断状态
  应用补丁.py            把 patched.py 铺到两处，并校验版本
  cordis.patch.yml      值班轮的最小权限 profile 补丁
  duty-settings.example.yaml  值班轮专用 settings（单模型/单路由）
```

## 改了什么

只有一处：`vendor/bilibili-mcp/mcp_server.py` —— **+211 / −1 行**，三块改动：

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
   `bili_video_zones` 无论白名单怎么写都放行 —— 都是**只读榜单接口**，安全；
   而白名单是插件侧 `index.js` 生成的，要改它就得改插件 + 重启 DSH，在这里放行能立刻生效。
   > `bili_reply`（发评论）**仍然被白名单挡着**，该挡的没漏。

> ⚠️ 曾经的第三处改动（`index.js` 里钉值班轮模型）已**回退**：`agent-default-model` 是
> 「settings 用户层 > 组合配置」，那段代码永远不生效。模型路由改由 `duty-settings.yaml` 负责。

## 怎么用

```bash
python patches/应用补丁.py --check    # 只看状态
python patches/应用补丁.py            # 应用（幂等，可重复跑）
python patches/应用补丁.py --revert   # 用 .orig-* 备份还原
```

脚本会把补丁铺到**两个位置**：

1. `<home>/.dsh/profiles/web/node_modules/dsh-bili-scroll/vendor/bilibili-mcp/mcp_server.py`
2. `<home>/.dsh/bili-duty/mcp_server.py`

**两处必须一致**——插件启动时 `ensureHomeFiles` 会拿插件包里的那份覆盖家目录那份，
只有两份字节相同才会"本来就是同一份"而跳过。

## 状态判断

应用脚本不比 patch 上下文，而是比 **sha256**：

| 目标文件指纹 | 判定 | 动作 |
|---|---|---|
`== base` | 可应用 | 备份 `.orig-<时间戳>` 后覆盖 |
`== patched` | 已应用 | 跳过（幂等） |
其它 | **上游变了 / 被人改过** | **拒绝动手**，让你对照 `.patch` 手工合并 |

## 上游升级了怎么办

1. 新版本装好后，`python patches/应用补丁.py --check` 会报 `⚠️ 上游变了/被改过`
2. 从新版本里取出 `mcp_server.py` 存成 `mcp_server/base-<新版本>.py`
3. 把 `patched.py` 里的两块改动（搜一段 `刷一轮的用法`，一段 `投递闸门`）手工合并进新文件
4. 重跑 `生成补丁集.py`（见 `bili-profile/_dev/`）刷新 `.patch` 和 `SHA256.txt`

因为我们只改一个文件的两块**互不相干**的区域，这个合并通常五分钟。

## 为什么不用 `git apply` 作为应用方式

补丁要打到 `node_modules/` 里，那不是 git 仓库，`git apply` 会报
`fatal: this operation must be run in a work tree`。而按指纹整文件铺等价、更可控，
还能顺手给"上游变了"这个状态一个明确的判定。

> `mcp_server.patch` 依旧是**真补丁**——在临时 git 仓里 `git apply` 后指纹和 `patched.py`
> 完全一致，这一点每次生成时都会被验证。
>
> ⚠️ 生成时 `.patch` 必须以 **LF** 写入：Windows 上 Python 的 `write_text` 默认把 `\n` 翻成
> `\r\n`，而它描述的文件是 LF ⇒ 行尾对不上，`git apply` 全部失败（踩过）。
