# bili-duty profile 的最小权限补丁（示例）

值班轮 = 一个**没人看守**的 headless 轮。默认的 `headless` profile 只关了
`hmr / credentials / authorization / deepseek-account`，工具一个没动 ⇒ 那一轮手里握着整台电脑：
任意读写文件、跑命令、抓任意 URL、起子代理绕过限制。

这里的思路不是"叮嘱它别乱来"，而是**根本不给它那些手**：只留 B站 MCP 的几只只读工具，
报告/判重表/归档走固定路径的窄口工具。

用法：把下面内容存成 `~/.dsh/profiles/bili-duty/cordis.patch.yml`。

```yaml
# ── headless 默认关掉、值班轮要补开的（模型要用账号额度）────────────────
- id: credentials
  disabled: false
- id: authorization
  disabled: false
- id: deepseek-account
  disabled: false
- id: agent-default-model
  config:
    provider: deepseek-account
    model: deepseek-flash

# ── 值班轮专用的 settings 文件 ──────────────────────────────────────────
# ⭐ `agent-default-model` 这类服务的「用户层」永远盖住组合配置 ⇒
#    只要 ~/.dsh/settings.yaml 里有 agent-default-model，上面那条 config
#    和插件 overlay 里写的 agent-default-model **都不生效**。
#    把 settings 文件换成值班轮专属的一份，才能让值班轮单独选模型/路由，
#    主会话照旧读 ~/.dsh/settings.yaml，互不干扰。
- id: settings
  config:
    path: '<你的家目录>/.dsh/bili-duty/duty-settings.yaml'

# ── 命令执行 ────────────────────────────────────────────────────────────
- id: tool-bash
  disabled: true
- id: tool-pwsh
  disabled: true
- id: tool-jobs
  disabled: true
- id: jobs
  disabled: true
- id: tool-ralph
  disabled: true

# ── 文件系统：读 / 写 / 搜 —— 一个都不留 ────────────────────────────────
- id: tool-fs
  disabled: true
- id: tool-fs-search
  disabled: true

# ── 联网：B站 数据走 MCP，不需要它自己抓网页 ────────────────────────────
- id: tool-web
  disabled: true
- id: web-fetch-http
  disabled: true
- id: web-search-deepseek
  disabled: true

# ── 子代理 / 工作流：都能绕开工具限制 ───────────────────────────────────
- id: tool-subagent
  disabled: true
- id: tool-subagent-fork
  disabled: true
- id: tool-subagent-control
  disabled: true
- id: tool-subagent-list-agents
  disabled: true
- id: subagent
  disabled: true
- id: subagent-fork-in-process
  disabled: true
- id: subagent-spawn-in-process
  disabled: true
- id: workflow-ptc
  disabled: true
- id: ptc-runtime
  disabled: true
- id: tool-workflow
  disabled: true
# ⚠️ 漏了这条会起不来：`workflow-worker-thread` 等的是 subagents 服务，
#    上面把 subagent 禁掉后它一直 pending ⇒ plugin tree failed to load ⇒ 整轮 exit 1
- id: workflow-worker-thread
  disabled: true

# ── 技能：会读文件 ──────────────────────────────────────────────────────
- id: skill
  disabled: true
- id: skill-filesystem
  disabled: true
- id: skill-badge
  disabled: true
- id: tool-skill
  disabled: true

# ── 自动读 AGENTS.md（会把上级目录的私人设定塞进上下文）──────────────
- id: agent-instructions
  disabled: true

# ── 装插件 / 热重载 / 改配置 ─────────────────────────────────────────────
- id: tool-plugin-manager
  disabled: true
- id: plugin-manager
  disabled: true
- id: hmr
  disabled: true

# ── 目标循环 / 计划模式 / 待办 ───────────────────────────────────────────
- id: goal
  disabled: true
- id: command-goal
  disabled: true
- id: tool-goal
  disabled: true
- id: goal-round-driver
  disabled: true
- id: plan-mode
  disabled: true
- id: tool-todo
  disabled: true

# ── MCP 资源读取 ─────────────────────────────────────────────────────────
- id: mcp-resources
  disabled: true
```

## 注意

- 上面的 `id` 都是 `dsh --profile headless --dump-default-config` 里的**真实条目**，
  写错 id 会让 profile 组不起来（所以别凭印象加）。
- 插件 `dsh-bili-scroll` 还会自己往这一轮叠一份 overlay（把 B站 MCP 挂上去、
  并把 `BILI_MCP_TOOLS` 白名单写进 env —— MCP 那头**不在白名单里的工具根本不注册**，
  连名字都不给它看见）。
