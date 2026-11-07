#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
私信控制台 —— 把「小号 ↔ 大号」的私信当命令行用（纯本地，不花 token）。

用法（一般不用手动跑，计划任务每 2 分钟扫一次）：
    python 私信控制台.py            # 扫一次：有新消息就跑评分，有 /命令 就执行并回私信
    python 私信控制台.py --dry --simulate "/debug"   # 本地演练：只打印回复，不发私信

支持的命令（发 `/help` 看）：
    /debug            总览：关键词、台账、缓冲区、今天额度、路由
    /kw               只看关键词
    /kw add 词 [词…]   加关键词
    /kw del 词 [词…]   删关键词
    /list             最近 8 条台账
    /buf              缓冲区（纯文字评价）现状
    /learn            立刻把缓冲区学一遍
    /last             今天挑了哪些
    /status           额度 / 窗口 / 判重表
    /cost             今天花了多少
"""
from __future__ import annotations

import asyncio
import datetime
import json
import os
import pathlib
import re
import subprocess
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
LOCAL = {}
try:
    LOCAL = json.loads((HERE / "local.json").read_text(encoding="utf-8"))
except Exception:
    LOCAL = {}
DUTY = pathlib.Path(os.environ.get("BILI_DUTY_HOME") or LOCAL.get("dutyHome")
                    or (pathlib.Path.home() / ".dsh" / "bili-duty"))


class _NullIO:
    """计划任务用 pythonw.exe 跑（不弹黑窗口）时 sys.stdout/stderr 是 None ——
    print() 会直接 AttributeError 崩掉，所以先塞个哑对象。"""

    def write(self, *_a, **_k):
        return 0

    def flush(self):
        pass

    def reconfigure(self, **_k):
        pass

    def isatty(self):
        return False


if sys.stdout is None:
    sys.stdout = _NullIO()
if sys.stderr is None:
    sys.stderr = _NullIO()

# ⚠️ 计划任务里没有控制台，stdout 默认走 GBK —— 打印 emoji（👍/👎）会 UnicodeEncodeError 直接崩
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
OWNER = int(os.environ.get("BILI_OWNER_UID") or LOCAL.get("ownerUid") or 0)
WORKSPACE = pathlib.Path(LOCAL.get("workspace") or HERE)
SCORING = WORKSPACE / "评分.mjs"
BILL = WORKSPACE / "刷视频账单.mjs"
STATE = DUTY / "console-state.json"
CHATLOG = DUTY / "chat-history.jsonl"      # 私信对话上下文（最近几轮拼进提示词）
RECONCILE = WORKSPACE / "对账补记.mjs"
PREF = WORKSPACE / "偏好.mjs"
CFG = DUTY / "config.json"
LEDGER = DUTY / "ratings.jsonl"
SEEN = DUTY / "seen.md"
OUT = DUTY / "out"

DM_LIMIT = 480

# ⭐ --simulate 是**只读预览**：所有改配置的函数都要能被它拦住
#   （踩过：演练 `/gate maxlen 60` 把真值写进去了 ✗）
SIMULATE = False

def _persist(path, obj) -> None:
    if SIMULATE:
        return
    write_json(path, obj)
          # 单条私信的字数上限（实测 500 会顶；留点余量）
MAX_CHUNKS = 4

NODE = os.environ.get("BILI_NODE") or LOCAL.get("nodeExe") or "node"
DSH_BIN = os.environ.get("BILI_DSH_BIN") or LOCAL.get("dshBin") or ""
OVERLAY = DUTY / "headless-overlay.yml"
CHAT_OVERLAY = DUTY / "console-chat-overlay.yml"

BJ = datetime.timezone(datetime.timedelta(hours=8))


# ── 小工具 ────────────────────────────────────────────────────────────────
# ⚠️ pythonw.exe 跑的时候**没有控制台**，这时再 spawn 一个控制台程序（node.exe / python.exe）
#    Windows 会**给它新开一个黑窗口**弹出来 ✗ ⇒ 一律加 CREATE_NO_WINDOW
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def run_proc(cmd, **kw):
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    return subprocess.run(cmd, creationflags=CREATE_NO_WINDOW, **kw)


def now_bj() -> datetime.datetime:
    return datetime.datetime.now(BJ)


def read_json(path: pathlib.Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: pathlib.Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ledger() -> list[dict]:
    rows = []
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    return rows


def keywords() -> list[str]:
    return list((read_json(CFG, {}) or {}).get("keywords") or [])


def patch_keywords(add=(), remove=()) -> tuple[list[str], list[str], list[str]]:
    cfg = read_json(CFG, None)
    if cfg is None:
        raise RuntimeError("读不到 config.json")
    before = list(cfg.get("keywords") or [])
    nxt = [k for k in before if k not in remove]
    added = []
    for w in add:
        w = str(w).strip()
        if not w or w in nxt:
            continue
        nxt.append(w)
        added.append(w)
    removed = [k for k in before if k not in nxt]
    if added or removed:
        cfg["keywords"] = nxt
        s = cfg.get("_set")
        if isinstance(s, list) and "keywords" not in s:
            s.append("keywords")
        _persist(CFG, cfg)
        try:
            with (DUTY / "keyword-log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "at": now_bj().isoformat(), "src": "console", "added": added, "removed": removed,
                    "keywords": nxt,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return before, nxt, added or removed


def patch_exclude(add=(), remove=()) -> tuple[list[str], list[str], list[str]]:
    """排除词（excludeWords）—— 插件每轮都会把它塞进值班提示词，
    标题 / UP 名 / 简介里出现就整条跳过，比删关键词温和得多（2026-11-05 加）。"""
    cfg = read_json(CFG, None)
    if cfg is None:
        raise RuntimeError("读不到 config.json")
    before = list(cfg.get("excludeWords") or [])
    nxt = [k for k in before if k not in remove]
    added = []
    for w in add:
        w = str(w).strip()
        if not w or w in nxt:
            continue
        nxt.append(w)
        added.append(w)
    removed = [k for k in before if k not in nxt]
    if added or removed:
        cfg["excludeWords"] = nxt
        s = cfg.get("_set")
        if isinstance(s, list) and "excludeWords" not in s:
            s.append("excludeWords")
        _persist(CFG, cfg)
        try:
            with (DUTY / "keyword-log.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "at": now_bj().isoformat(), "src": "console-mute",
                    "added": added, "removed": removed, "excludeWords": nxt,
                }, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return before, nxt, added or removed


def exclude_words() -> list[str]:
    return list((read_json(CFG, {}) or {}).get("excludeWords") or [])


PREFS = DUTY / "prefs.json"


# ══════════════════════════════════════════════════════════════════════════
#  追问：11/-1 分但提不出词时，把候选摆到你面前（2026-11-05 加）
# ══════════════════════════════════════════════════════════════════════════
# 由 评分.mjs 写 待追问.json；这里负责：发出去 → 收你的回答 → 落到关键词 / 判据统计。
# 回法：`1 3`（裸数字，只有存在挂起问题时才当答案）、`/答 1 3`、或直接说一句。
ASK_FILE = DUTY / "待追问.json"
TAGSTAT = DUTY / "判据统计.json"
ASK_TIMEOUT_H = 24


def read_ask():
    q = read_json(ASK_FILE, None)
    if not isinstance(q, dict) or q.get("answered"):
        return None
    try:
        ts = datetime.datetime.fromisoformat(str(q.get("at")).replace("Z", "+00:00"))
        if (datetime.datetime.now(datetime.timezone.utc) - ts).total_seconds() > ASK_TIMEOUT_H * 3600:
            return None      # 过期就静默丢掉，不追问第二遍
    except Exception:
        pass
    return q


def write_ask(q) -> None:
    write_json(ASK_FILE, q)


def format_ask(q: dict) -> str:
    kind = "好在哪" if q.get("kind") == "good" else "差在哪"
    tags = q.get("tags") or []
    words = q.get("words") or []
    if not tags and not words:
        return ""
    lines = [f"《{str(q.get('title') or '')[:26]}》记了 {q.get('score')} 分，但我没抓到搜索方向。",
             f"{kind}？回数字，可多选：", ""]
    if tags:
        lines.append("【" + ("怎么好" if q.get("kind") == "good" else "差在哪") + "】" +
                     "  ".join(f"{i + 1} {t}" for i, t in enumerate(tags)))
    if words:
        base = len(tags)
        lines.append("【加哪个词】" + "  ".join(f"{base + i + 1} {w}" for i, w in enumerate(words)))
    lines += ["", "也可以直接说一句，我自己提炼。"]
    return "\n".join(lines)


ASK_NUMS = re.compile(r"^[\d\s,，、+＋]+$")

# ⭐⭐ 2026-11-06：私信里也能直接下「加词 / 删词」指令。
#   起因：使用者发「4 · 加词：可玩性强」想给第 4 条加个搜索词，
#   结果被 looks_like_review 当成"文字评价"静默记账 ——
#   词没加、追问没关、一个字都没回 ✗
#   指令优先级最高：**指令 > 追问回答 > 打分 > 闲聊**。
KW_CMD = re.compile(
    r"(加词|加个词|加关键词|添加关键词|删词|删掉词|去掉词|删关键词|删掉关键词)"
    r"\s*(?:[：:]\s*|\s+)(.+)$"
)
# 指令前面常带一个条目号（`4 ·` / `4、` / `[4]`），只是指代哪条视频，剥掉
ITEM_PREFIX = re.compile(r"^\s*\[?\d{1,2}\]?\s*[·．.、,，:：\-\s]*")


def parse_kw_command(text: str):
    """返回 ('add'|'del', ['词', …]) 或 None"""
    raw = (text or "").strip()
    if not raw or len(raw) > 60:
        return None
    t = ITEM_PREFIX.sub("", to_half(raw)).strip()
    m = KW_CMD.search(t)
    if not m:
        return None
    op = "del" if m.group(1).startswith(("删", "去掉")) else "add"
    words = [w.strip() for w in re.split(r"[,，、;；/|\s]+", m.group(2)) if w.strip()]
    words = [w for w in words if 1 < len(w) <= 12]
    return (op, words) if words else None


def handle_kw_command(text: str, dry: bool) -> str:
    """执行加词/删词指令，顺手把挂着的追问关掉（这就是它在回答"加哪个词"）"""
    op, words = parse_kw_command(text)
    before, after, changed = patch_keywords(
        add=(words if op == "add" else ()), remove=(words if op == "del" else ()))
    if op == "add":
        hit = [w for w in words if w in after and w not in before]
    else:
        hit = [w for w in words if w in before and w not in after]

    q = read_ask()
    if q:
        q["answered"] = True
        q["answer"] = {"tags": [], "words": hit if op == "add" else [],
                       "text": str(text)[:60], "at": now_bj().isoformat(timespec="seconds")}
        if not dry:
            write_ask(q)

    if not dry:
        try:
            run_proc([NODE, str(PREF)], timeout=60)      # 立刻渲染进章程
        except Exception:
            pass
        append_log(f"关键词指令 {op} {words} → {after}")

    if not hit:
        tail = "已经在关键词里了" if op == "add" else "本来就不在关键词里"
        return f"{'、'.join(words)} {tail}\n现在（{len(after)}）：{' · '.join(after)}"
    head = f"关键词 +{'、'.join(hit)}" if op == "add" else f"关键词 -{'、'.join(hit)}"
    return head + f"\n现在（{len(after)}）：{' · '.join(after)}" + "\n（下一轮挑片就用新的）"


# ── 文字评价的「检查 → 反馈」链（2026-11-06）────────────────────────────
# 起因：文字评价以前静默落进缓冲区 —— 使用者连着问"为什么没有回复"。
# 现在评分脚本会给机器行，这里翻成人话回执；再加个 /查 让人预检。

def parse_feedback(out: str):
    """从 评分.mjs 的 stdout 里抠出 __FEEDBACK__ 那行"""
    for line in (out or "").splitlines():
        if line.startswith("__FEEDBACK__ "):
            try:
                return json.loads(line[len("__FEEDBACK__ "):])
            except Exception:
                return None
    return None


def format_feedback(fb: dict) -> str:
    """把评分结果翻成一句人话（空字符串 = 不用回执）"""
    if not fb:
        return ""
    parts = []
    scores = fb.get("scores") or []
    texts = fb.get("texts") or []
    if scores:
        bits = []
        for s in scores[:8]:
            v = s.get("score")
            bits.append("★11" if v == 11 else ("✗-1" if v == -1 else f"{v}分"))
        parts.append(f"记下 {len(scores)} 条打分：" + " · ".join(bits))
    if texts:
        n = len(texts)
        sample = str(texts[0].get("note") or "")[:16]
        parts.append(f"记下 {n} 条文字评价（「{sample}」…）→ 进缓冲区")
    if fb.get("added"):
        parts.append("关键词 +" + "、".join(fb["added"]))
    if fb.get("removed"):
        parts.append("关键词 -" + "、".join(fb["removed"]))
    if fb.get("asks"):
        parts.append(f"{fb['asks']} 条提不出词，等会儿追问你")
    return "；".join(parts)


def cmd_check(args: list[str]) -> str:
    """预检：这句话我会怎么理解？**只看不动**（不记账、不改配置）"""
    text = " ".join(args).strip()
    if not text:
        return ("用法：/查 4 加词：可玩性强　或　/查 4 讲得真清楚\n"
                "（只告诉我会怎么理解，什么都不改）")
    out = [f"【预检】{text}", ""]
    acted = False

    kwc = parse_kw_command(text)
    if kwc:
        op, words = kwc
        out.append(f"→ 关键词指令：{'加' if op == 'add' else '删'}「{'、'.join(words)}」"
                   "（真发的话会立刻执行并回执）")
        acted = True

    q = read_ask()
    ans = parse_ask_answer(text, q) if q else None
    if ans:
        kind, val = ans
        if not q:
            out.append("→ 看着像「回答追问」，但现在没有挂起的问题 ⇒ 会按评价处理")
        elif kind == "nums":
            out.append(f"→ 回答追问：编号 {val}")
        else:
            out.append("→ 回答追问：自由文本（我会再提炼一次词）")
        acted = True

    flat = to_half(text)
    if not acted:
        if REVIEW_PAIR.search(flat):
            out.append("→ 算「打分」：交给评分脚本记账，我会回一条回执")
        elif REVIEW_TEXT.match(flat):
            out.append("→ 算「文字评价」：记给对应条目、进缓冲区，我会回一条回执")
            out.append("  想顺手加词就说「加词：X」（比写长句有用）")
        else:
            out.append("→ 不算命令、也不是评价 ⇒ 会当成聊天，起一轮来回答你")

    out += ["", "（以上只是预检，什么都没改）"]
    return "\n".join(out)


def to_half(s: str) -> str:
    """全角 → 半角，**等长映射**（中文标点保持不变）。
    ⚠️ 不能用 unicodedata.normalize('NFKC')：它会把中文逗号 `，` 改成 `,`，
       等于篡改使用者原话（评分.mjs 那边踩过同一个坑）"""
    out = []
    for ch in str(s or ""):
        o = ord(ch)
        if 0xFF01 <= o <= 0xFF5E:          # 全角 ASCII
            out.append(chr(o - 0xFEE0))
        elif ch == "\u3000":               # 全角空格
            out.append(" ")
        elif ch == "\u2212":               # 数学减号
            out.append("-")
        else:
            out.append(ch)
    return "".join(out)


def parse_ask_answer(text: str, q: dict):
    """返回 ('nums', [1,3]) / ('text', '自己的话') / None（不是回答）
    ⚠️ 打分（`1=10 3=9` / `4 调色板真舒服`）**必须原样放行**，不能被当成"自由文本回答"吞掉
    ⚠️ 自由文本要返回**原话**（只归一化用于判断，不改写）
    """
    raw = (text or "").strip()
    if not raw:
        return None
    t = to_half(raw)
    if t.startswith(("/答", "/a ", "/answer")):
        t = re.sub(r"^/(答|a|answer)\s*", "", t).strip()
        if not t:
            return None
    if ASK_NUMS.match(t):
        nums = [int(x) for x in re.findall(r"\d+", t)]
        return ("nums", nums) if nums else None
    if REVIEW_PAIR.search(t) or REVIEW_TEXT.match(t):
        return None                       # 这是打分，交给 评分.mjs
    return ("text", raw)


def record_ask_answer(q: dict, kind: str, value, dry: bool) -> str:
    tags = list(q.get("tags") or [])
    words = list(q.get("words") or [])
    picked_tags, picked_words, note = [], [], ""
    if kind == "nums":
        for n in value:
            if 1 <= n <= len(tags):
                picked_tags.append(tags[n - 1])
            elif len(tags) < n <= len(tags) + len(words):
                picked_words.append(words[n - 1 - len(tags)])
        if not picked_tags and not picked_words:
            return f"这几个编号对不上（有效范围 1~{len(tags) + len(words)}），再发一次？"
    else:
        note = str(value)[:60]

    if not dry:
        if picked_tags:
            stats = read_json(TAGSTAT, {}) or {}
            for t in picked_tags:
                stats[t] = int(stats.get(t, 0)) + 1
            write_json(TAGSTAT, stats)
        if picked_words:
            patch_keywords(add=picked_words)
        q["answered"] = True
        q["answer"] = {"tags": picked_tags, "words": picked_words, "text": note,
                       "at": now_bj().isoformat(timespec="seconds")}
        write_ask(q)
        append_log(f"追问已回答 {q.get('bvid')}：tags={picked_tags} words={picked_words} text={note[:20]}")
        # 自由文本 ⇒ 交给 评分.mjs 用真正的提词逻辑提炼一次（幂等，带 applied 标记）
        if note and SCORING.exists():
            try:
                r = run_proc([NODE, str(SCORING), '--ask-apply'], timeout=120)
                out = (r.stdout or '').strip()
                if out:
                    append_log("追问提炼：" + out.replace("\n", " / ")[:160])
            except Exception as e:
                append_log(f"追问提炼跑挂：{e}")

    bits = []
    if picked_tags:
        bits.append("记住了：" + "、".join(picked_tags) + "（以后就用它判断好不好）")
    if picked_words:
        bits.append("关键词加了：" + "、".join(picked_words))
    if note:
        bits.append(f"收到「{note}」——下次按这个方向再提炼")
    if not bits:
        bits.append("收到，只记分不改进关键词。")
    return "\n".join(bits)


def read_prefs() -> dict:
    return read_json(PREFS, {}) or {}


def patch_prefs(**kw) -> dict:
    cur = read_prefs()
    cur.update({k: v for k, v in kw.items() if v is not None})
    _persist(PREFS, cur)
    return cur


def cmd_gate(args: list[str]) -> str:
    """看/改投递闸门 —— 这一层是**代码级**的：命中就真的发不出去"""
    cur = read_prefs()
    num = [a for a in args if re.fullmatch(r"\d+", a or "")]
    op = (args[0].lower() if args else "")
    if op in ("maxlen", "len", "时长") and num:
        c = patch_prefs(maxDurationMin=int(num[0]))
        return f"时长上限 = {c['maxDurationMin']} 分钟（0 = 不限；合集/课程始终豁免）"
    if op in ("minplay", "play", "播放") and num:
        c = patch_prefs(minPlay=int(num[0]))
        return f"播放量下限 = {c['minPlay']}（0 = 不限）"
    if op in ("off", "关"):
        patch_prefs(maxDurationMin=0, minPlay=0)
        return "时长/播放量限制已关（屏蔽词和屏蔽 UP 还生效，用 /mute /ban /unmute 管）"
    words = exclude_words()
    ups = cur.get("banUps") or []
    return (
        "【投递闸门】命中就真的发不出去（是拦，不是建议）\n"
        f"屏蔽词 {len(words)}：{' · '.join(words) or '（空）'}\n"
        f"屏蔽 UP {len(ups)}：{' · '.join(ups) or '（空）'}\n"
        f"时长上限 {cur.get('maxDurationMin') or 0} 分钟（0=不限，合集/课程豁免）\n"
        f"播放量下限 {cur.get('minPlay') or 0}（0=不限）\n"
        "改：/mute 词 ｜ /ban UP名 ｜ /gate maxlen 60 ｜ /gate minplay 10000 ｜ /gate off"
    )



# ══════════════════════════════════════════════════════════════════════════
#  /give N —— 立刻刷一轮，只挑 N 条发给你（2026-11-06 加）
# ══════════════════════════════════════════════════════════════════════════
# 为什么是"起一轮值班"而不是自己搜：挑片、读字幕、投递闸门、私信发送全在
# 章程和 mcp_server 的两道闸里，自己搜等于把那一整套重写一遍、还绕过了所有闸。
GIVE_MAX = 10            # 一次最多要几条（再多没意义，也烧钱）
GIVE_COOLDOWN_MIN = 5    # 两次 /give 之间冷却（防手滑连点）


def build_give_prompt(n: int) -> str:
    """拼「手动跑一轮、只挑 N 条」的提示词。

    ⚠️ 章程必须**内联**：值班轮是最小权限 profile，没有文件系统，
       那一轮根本读不了 duty.md（插件 index.js 的 promptFor 也这么干）。
    """
    cfg = read_json(CFG, {}) or {}
    today = now_bj().strftime("%Y-%m-%d")
    out = DUTY / "out" / f"{today}.md"
    kws = " · ".join(cfg.get("keywords") or []) or "（空，按章程里的方向自己找）"
    ex = [str(x).strip() for x in (cfg.get("excludeWords") or []) if str(x).strip()]

    head = ["你是这个账号的 B站 助手。下面是**值班章程** —— 严格按它执行：", ""]
    tail = [
        "",
        f"⭐ 这一轮是**手动触发（私信 /give {n}）**：现在就刷，不占今天的自动额度。",
        f"⭐ **只挑 {n} 条**，挑完就收 —— 别多挑，也别把全天要看的量一次挑光。",
        f"把报告写到 {out}；那份今天可能已经有内容，有就**追加到末尾**、别覆盖。",
        "⭐ 报告里每挑中一条，第一行写成 `### BV号`（宿主就数这些标题行算挑了几条）。",
        f"搜索关键词：{kws}",
    ]
    if ex:
        tail.append(f"⛔ 排除词（先过这一关）：{'、'.join(ex)} —— 标题/UP名/简介里出现这些词的整条跳过。")
    if str(cfg.get("dmMode") or "") == "only":
        tail.append("投递：只私信（发完不用评论）。")
    tail.append(
        f"挑完把 {n} 条一次性私信发给我：每条给 BV 号 + 标题 + 一句为什么值得看。"
        "实在发不出去就把原因写进报告。")

    try:
        charter = (DUTY / "duty.md").read_text(encoding="utf-8").replace("<家目录>", str(DUTY))
    except Exception:
        charter = f"（章程没读到 —— 按你平时的方式刷一轮；家目录 = {DUTY}）"

    # Windows 命令行上限 32767 字符：超了就截章程，别让 spawn 直接失败
    fixed = len("\n".join(head)) + len("\n".join(tail)) + 200
    budget = max(2000, 30000 - fixed)
    if len(charter) > budget:
        charter = charter[:budget] + "\n（章程过长，已截断）"
    return "\n".join(head + [charter] + tail)


def spawn_round(prompt: str) -> int:
    """起一轮值班，**不等它跑完**，返回 pid。

    一轮要 2~5 分钟；控制台每分钟扫一次，同步等会把扫描卡死。
    """
    cmd = [NODE, DSH_BIN, "--profile", "bili-duty", "--patch", str(OVERLAY), prompt]
    env = {**os.environ, "BILI_DUTY_HOME": str(DUTY),
           "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    flags = (0x00000008 | 0x08000000) if os.name == "nt" else 0   # DETACHED | CREATE_NO_WINDOW
    log = (DUTY / "duty.log").open("a", encoding="utf-8", errors="replace")
    try:
        proc = subprocess.Popen(cmd, cwd=str(DUTY), env=env,
                                stdin=subprocess.DEVNULL,
                                stdout=log, stderr=subprocess.STDOUT,
                                creationflags=flags)
    finally:
        log.close()
    return proc.pid


def cmd_give(args: list[str]) -> str:
    """/give N —— 立刻刷一轮，只挑 N 条推荐给你。"""
    import time as _t

    n = 0
    for a in args:
        if re.fullmatch(r"\d+", (a or "").strip()):
            n = int(a.strip())
            break
    if n <= 0:
        return (f"用法：/give 5\n立刻刷一轮，只挑 N 条发给你（1~{GIVE_MAX}）；"
                "不占今天的自动额度，跑完会私信。")
    n = max(1, min(GIVE_MAX, n))

    if duty_busy():
        return "正在刷着一轮了 —— 等它跑完再发 /give（不然两边抢 B站 请求，都会变慢）。"
    if not OVERLAY.exists():
        return f"找不到值班轮用的 overlay：{OVERLAY}\n先在 DSH 里点一次「跑一轮」，它会生成这份文件。"

    st = read_json(STATE, {}) or {}
    last = float(st.get("lastGiveAt") or 0)
    if last:
        left = GIVE_COOLDOWN_MIN * 60 - (_t.time() - last)
        if left > 0:
            return (f"刚给过一轮（{int((_t.time() - last) // 60)} 分钟前），"
                    f"再等 {int(left // 60) + 1} 分钟 —— 防手滑连点把额度烧光。")

    if SIMULATE:
        return (f"（预览模式）会起一轮值班，挑 {n} 条，报告写进 out/{now_bj().strftime('%Y-%m-%d')}.md\n"
                f"命令：{' '.join([NODE, DSH_BIN, '--profile', 'bili-duty', '--patch', str(OVERLAY)])} …")

    try:
        pid = spawn_round(build_give_prompt(n))
    except Exception as e:
        append_log(f"give 起轮失败：{e}")
        return f"起轮失败：{e}"

    st["lastGiveAt"] = _t.time()
    write_json(STATE, st)
    append_log(f"give {n} → pid {pid}")
    return (f"已开刷：挑 {n} 条（pid {pid}）。\n"
            f"跑完它会自己私信发过来，完整报告写进 out/{now_bj().strftime('%Y-%m-%d')}.md。\n"
            "大概 2~5 分钟；这期间别再发 /give。")


def cmds():
    return {
        "debug": cmd_debug, "kw": cmd_kw, "list": cmd_list,
        "buf": cmd_buf, "learn": cmd_learn, "last": cmd_last,
        "status": cmd_status, "cost": cmd_cost, "help": cmd_help,
        "mute": cmd_mute, "unmute": cmd_unmute, "ban": cmd_ban, "gate": cmd_gate,
        "查": cmd_check, "check": cmd_check,
        "give": cmd_give,
    }


CONSOLE_LOG = DUTY / "console.log"
LOCK = DUTY / "console.lock"


def acquire_lock(ttl: int = 300) -> bool:
    """跨进程互斥：计划任务每 1 分钟一次，碰上上一轮还没跑完就会**重复回同一条命令**
    （2026-11-05 实测：/kw 回了两次）。用 O_EXCL 建锁文件，拿不到就跳过本次。"""
    import time as _t
    try:
        if LOCK.exists():
            try:
                age = _t.time() - LOCK.stat().st_mtime
            except Exception:
                age = 0
            if age < ttl:
                return False
            try:
                LOCK.unlink()
            except Exception:
                pass
        fd = os.open(str(LOCK), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except Exception:
        return True          # 建不了锁就照常跑（fail-open），别让控制台瘫掉


def release_lock() -> None:
    try:
        LOCK.unlink()
    except Exception:
        pass


def append_log(line: str) -> None:
    """计划任务没有控制台，命令往来写进 console.log 方便回头查（一条一行，换行压成 ·）"""
    line = " · ".join(str(line).splitlines())
    try:
        try:
            if CONSOLE_LOG.exists() and CONSOLE_LOG.stat().st_size > 200_000:
                CONSOLE_LOG.write_text(CONSOLE_LOG.read_text(encoding="utf-8", errors="replace")[-100_000:],
                                       encoding="utf-8")
        except Exception:
            pass
        with CONSOLE_LOG.open("a", encoding="utf-8") as f:
            f.write(f"[{now_bj().isoformat(timespec='seconds')}] {line}\n")
    except Exception:
        pass


# ── 各命令 ────────────────────────────────────────────────────────────────
def cmd_mute(args: list[str]) -> str:
    """软黑名单：标题/UP/简介出现这个词就整条跳过（不删关键词、不影响搜索方向）"""
    if not args:
        w = exclude_words()
        return "【排除词】" + (f"（{len(w)}）\n" + " · ".join(w) if w else "（空）") + \
               "\n加：/mute 考研 ｜ 删：/unmute 考研 ｜ 别推某个UP：/ban UP名"
    before, after, changed = patch_exclude(add=args)
    newly = [w for w in args if w in after and w not in before]
    if not newly:
        return f"这几个已经在排除词里了：{'、'.join(args)}\n现在：{' · '.join(after)}"
    return f"已屏蔽：{'、'.join(newly)}\n现在（{len(after)}）：{' · '.join(after)}"


def cmd_unmute(args: list[str]) -> str:
    if not args:
        return "用法：/unmute 词（把某个词从排除词里放出来）｜/mute 看全部"
    before, after, changed = patch_exclude(remove=args)
    hit = [w for w in args if w in before]
    if not hit:
        return f"没删掉：{'、'.join(args)} 不在里面\n现在：{' · '.join(after)}"
    return f"已放出：{'、'.join(hit)}\n现在（{len(after)}）：{' · '.join(after)}"


def cmd_ban(args: list[str]) -> str:
    """按 UP 名屏蔽：**两处都写** —— excludeWords（进提示词，让模型少挑）
    和 prefs.json 的 banUps（进投递闸门，代码级拦死）"""
    if not args:
        return "用法：/ban UP名（这个 UP 的一律不推；一个词一个词加，别带空格）"
    before, after, changed = patch_exclude(add=args)
    cur = read_prefs()
    ups = list(cur.get("banUps") or [])
    for a in args:
        a = a.strip()
        if a and a not in ups:
            ups.append(a)
    patch_prefs(banUps=ups)
    newly = [w for w in args if w in after and w not in before]
    if not newly:
        return f"{'、'.join(args)} 已经在屏蔽名单里了（现在 UP {len(ups)} 个）"
    return (f"已屏蔽 UP：{'、'.join(newly)}\n"
            f"（提示词 + 投递闸门都生效：这个 UP 的视频发不出来）")


def cmd_help(_args) -> str:
    return (
        "【刷B站 · 私信命令】\n"
        "我按下面的间隔扫私信，**不是秒回**：托盘控制台开着时 ~15 秒，\n"
        "只有计划任务时 60 秒。等不了就别用私信 🔻\n"
        "\n【改状态】设好了就行，延迟无所谓\n"
        "/kw add|del 词   改搜索关键词\n"
        "/mute 词 /unmute 词 /ban UP名   屏蔽\n"
        "/gate maxlen N | minplay N | off   投递闸门\n"
        "/learn   立刻学一次缓冲区\n"
        "\n【看一眼】要即时的话去托盘控制台（窗口里点）\n"
        "/debug 总览 ｜ /status 额度与窗口\n"
        "/last 今天挑了哪些 ｜ /list 最近台账\n"
        "/buf 缓冲区 ｜ /cost 今天花多少\n"
        "/答 1 3 回答追问（也可以直接说一句）\n"
        "/give 5   立刻刷一轮，只挑 5 条给你（不占自动额度，跑完私信）\n"
        "\n【随时】/查 <一句话> 预检我会怎么理解（不记账、不改配置）\n"
        "私信里直接说「加词：X」「删词：X」也行，我立刻回执"
    )


def next_window() -> str:
    now = now_bj()
    hm = now.hour * 60 + now.minute
    if hm < 12 * 60:
        return "今天 12:00（中午谷时）"
    if hm < 14 * 60:
        return "现在就在中午窗口里"
    if hm < 18 * 60:
        return "今晚 18:00（夜间谷时）"
    return "现在就在夜间窗口里"


def cmd_debug(_args) -> str:
    kws = keywords()
    rows = ledger()
    scored = [r for r in rows if r.get("score") is not None]
    txt = [r for r in rows if r.get("score") is None]
    buf = [r for r in txt if not r.get("learned")]
    avg = (sum(int(r["score"]) for r in scored) / len(scored)) if scored else 0.0
    cfg = read_json(CFG, {}) or {}
    today = now_bj().strftime("%Y-%m-%d")
    picked = count_picked_today(today)
    kw_line = " · ".join(kws) if kws else "（空）"
    return (
        "【debug】\n"
        f"关键词({len(kws)})：{kw_line}\n"
        f"台账：{len(rows)} 条（高{sum(1 for r in scored if int(r['score']) >= 8)}"
        f" 中{sum(1 for r in scored if 3 < int(r['score']) < 8)}"
        f" 低{sum(1 for r in scored if int(r['score']) <= 3)}"
        f" 文字{len(txt)}）｜均分 {avg:.2f}\n"
        f"缓冲区：{len(buf)} 条待学 / 共 {len(txt)} 条\n"
        f"排除词：{len(exclude_words())} 个\n"
        f"今天：挑 {picked} 条 / 上限 {cfg.get('perDay', 0)}\n"
        f"路由：清华 · DeepSeek-V4-Flash-Vision-Exp\n"
        f"下一轮：{next_window()}"
    )


def cmd_kw(args: list[str]) -> str:
    if not args:
        kws = keywords()
        return "【关键词】" + (f"（{len(kws)}）\n" + " · ".join(kws) if kws else "（空）")
    op = args[0].lower()
    words = [w.strip() for w in args[1:] if w.strip()]
    if op in ("add", "加") and words:
        before, after, changed = patch_keywords(add=words)
        return f"关键词 +{'、'.join(changed)}\n现在：{' · '.join(after)}"
    if op in ("del", "rm", "remove", "删") and words:
        before, after, changed = patch_keywords(remove=words)
        hit = [w for w in words if w in before]
        if not hit:
            return f"没删掉：{'、'.join(words)} 不在里面\n现在：{' · '.join(after)}"
        return f"关键词 -{'、'.join(hit)}\n现在：{' · '.join(after)}"
    return "用法：/kw ｜ /kw add 词 ｜ /kw del 词"


def cmd_list(_args) -> str:
    rows = ledger()[-8:]
    if not rows:
        return "台账是空的。"
    out = ["【最近台账】"]
    for r in rows:
        s = r.get("score")
        tag = "文字" if s is None else ("★11" if s == 11 else ("✗-1" if s == -1 else f"{s}分"))
        out.append(f"{str(r.get('date'))[5:]} {tag:>4} {str(r.get('title') or '')[:24]}")
    return "\n".join(out)


def cmd_buf(_args) -> str:
    txt = [r for r in ledger() if r.get("score") is None]
    buf = [r for r in txt if not r.get("learned")]
    if not txt:
        return "缓冲区还是空的 —— 你回一句「4 画得真舒服」这种不打分的话，就会进缓冲区。"
    out = [f"【缓冲区】待学 {len(buf)} 条 · 已学 {len(txt) - len(buf)} 条（满 3 条自动学）"]
    for r in buf[-6:]:
        out.append(f"· {str(r.get('note'))[:40]}")
    if txt and buf:
        out.append("发 /learn 立刻学一次")
    return "\n".join(out)


def cmd_learn(_args) -> str:
    if not SCORING.exists():
        return f"找不到评分脚本：{SCORING}"
    try:
        r = run_proc([os.environ.get("BILI_NODE") or "node", str(SCORING), "--learn"], timeout=120)
        body = (r.stdout or "").strip() or (r.stderr or "").strip()
    except Exception as e:
        return f"学的时候出错了：{e}"
    lines = [l.strip() for l in body.splitlines() if l.strip()]
    keep = [l for l in lines if l.startswith(("消化了", "👍", "👎", "加进关键词", "从关键词删掉", "缓冲区", "关键词："))]
    return "【学习完成】\n" + ("\n".join(keep[:8]) if keep else "没有可学的新内容。")


def cmd_last(_args) -> str:
    today = now_bj().strftime("%Y-%m-%d")
    f = OUT / f"{today}.md"
    picked = count_picked_today(today)
    if not f.exists():
        return f"今天还没有报告（{today}）。判重表今天记了 {picked} 条「挑了」。"
    text = f.read_text(encoding="utf-8", errors="replace")
    blocks = re.findall(r"^###\s*(BV[0-9A-Za-z]{10})\s*\n+([^\n]+)", text, re.M)
    if not blocks:
        return f"今天的报告里还没有 `### BV` 条目。判重表今天记了 {picked} 条「挑了」。"
    out = [f"【今天挑了 {len(blocks)} 条】"]
    for bv, title in blocks[-8:]:
        t = re.sub(r"^[\s\-\*>]*\*{0,2}(标题|Title)\*{0,2}\s*[：:]\s*", "", title.strip())
        out.append(f"{t[:30]} https://b23.tv/{bv}")
    if picked and picked != len(blocks):
        out.append(f"⚠️ 判重表今天记了 {picked} 条「挑了」，报告里只有 {len(blocks)} 条 —— 有轮次没写进报告")
    return "\n".join(out)


def count_picked_today(today: str) -> int:
    """判重表里今天记了「挑了」的条数（宿主口径更可靠）"""
    n = 0
    if SEEN.exists():
        for line in SEEN.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith(f"| {today}") and "| 挑了 |" in line:
                n += 1
    return n


def cmd_status(_args) -> str:
    cfg = read_json(CFG, {}) or {}
    today = now_bj().strftime("%Y-%m-%d")
    picked = count_picked_today(today)
    now = now_bj()
    hm = now.hour * 60 + now.minute
    if 12 * 60 <= hm < 14 * 60:
        win = "在「中午谷时」窗口里"
    elif hm >= 18 * 60 or hm < 9 * 60:
        win = "在「晚上/夜间谷时」窗口里"
    else:
        win = "当前不在窗口（中午 12-14 / 夜间 18-09）"
    scan = last_scan_age()
    return (
        "【status】\n"
        f"今天：挑 {picked} / 上限 {cfg.get('perDay', 0)}\n"
        f"窗口：{win}\n"
        f"上次扫私信：{scan}\n"
        f"投递：{cfg.get('dmMode')} → uid {cfg.get('dmUid')}　"
        f"自动评论：{'开' if cfg.get('autoComment') else '关'}"
    )


def last_scan_age() -> str:
    """距上次扫描多久 —— 私信是异步通道，如实报新鲜度（2026-11-05 ①）"""
    st = read_json(STATE, {}) or {}
    t = st.get("lastScan")
    if not t:
        return "（还没记过）"
    try:
        dt = datetime.datetime.fromisoformat(str(t))
        sec = int((datetime.datetime.now(datetime.timezone.utc) - dt).total_seconds())
        if sec < 90:
            return f"{sec} 秒前"
        if sec < 5400:
            return f"{sec // 60} 分钟前"
        return f"{sec / 3600:.1f} 小时前 ⚠️ 可能已经停了"
    except Exception:
        return str(t)


def cmd_cost(_args) -> str:
    if not BILL.exists():
        return "找不到账单脚本。"
    try:
        r = run_proc([os.environ.get("BILI_NODE") or "node", str(BILL), "--today", "--json"], timeout=180)
        data = json.loads(r.stdout)
    except Exception as e:
        return f"查账单失败：{e}"
    t = data.get("total") or {}
    rounds = t.get("rounds", 0)
    picks = t.get("picks", 0)
    cost = t.get("costYuan", 0)
    free = t.get("freeRounds", 0)
    toks = (t.get("hitTokens", 0) or 0) + (t.get("missTokens", 0) or 0) + (t.get("outputTokens", 0) or 0)
    return (
        "【今天的花费】\n"
        f"DeepSeek 官方口径：¥{cost:.4f}（{rounds - free} 轮）\n"
        f"走清华网关：{free} 轮 · 不计价\n"
        f"挑中 {picks} 条 · 合计 {toks:,} tokens"
    )


# ── 「没有指令就当一个简化版对话」────────────────────────────────────────
# 只认命令太笨了：他随口问一句「今天有什么好看的」也该有人答。
# 但「1=10 3=9」「4 调色板真舒服」这种是**评价**，要交给 评分.mjs 记账，不该回话。

REVIEW_PAIR = re.compile(r"\d{1,2}\s*[=:：]\s*-?\d{1,2}")
REVIEW_TEXT = re.compile(r"^\s*\[?\d{1,2}\]?\s*[，,、.。:：\-\s]+\S")


def looks_like_review(text: str) -> bool:
    # ⚠️ NFKC 归一：中文输入法给的是全角 `＝`/`：`/数字，只认半角就会把「3＝11 有深度」
    #    当成闲聊回一句、11 分丢掉（2026-11-05 实测踩到）
    t = unicodedata.normalize("NFKC", (text or "").strip())
    if not t or len(t) > 40:
        return False
    return bool(REVIEW_PAIR.search(t) or REVIEW_TEXT.match(t))


def ensure_chat_overlay() -> pathlib.Path:
    """拿值班轮那份 overlay，但把 bili_send_message 从白名单里摘掉 ——
    这样对话轮**没手发私信**，一定由控制台代发，不会双发。"""
    text = OVERLAY.read_text(encoding="utf-8")
    text = re.sub(r",?\s*bili_send_message\b", "", text)
    CHAT_OVERLAY.write_text(text, encoding="utf-8")
    return CHAT_OVERLAY


def chat_prompt(text: str) -> str:
    persona = ""
    try:
        persona = (DUTY / "persona.md").read_text(encoding="utf-8")[:6000]
    except Exception:
        pass
    kws = keywords()
    today = now_bj().strftime("%Y-%m-%d")
    picked = count_picked_today(today)
    buf = len([r for r in ledger() if r.get("score") is None and not r.get("learned")])

    # ⭐ 带上最近几轮对话 —— 不然每句都是"第一次说话"，它会答非所问、重复问同样的事
    hist_lines = []
    for h in chat_history(5):
        hist_lines.append("他：" + str(h.get("user", ""))[:120])
        hist_lines.append("你：" + str(h.get("bot", ""))[:120])
    hist = ("（你们刚才聊过这几句，只当背景，别重复也别复述：\n" + "\n".join(hist_lines) + "\n）\n") if hist_lines else ""

    return (
        (f"（说话风格按这份人设来：\n{persona}\n）\n" if persona else "")
        + f"（当前状态，只供参考，别照抄、别念内部术语：搜索关键词 {' · '.join(kws) or '空'}；"
          f"今天已挑 {picked} 条；缓冲区 {buf} 条待学）\n"
        + hist
        + "账号持有者本人在 B站 私信里发来一句话：" + json.dumps(text, ensure_ascii=False) + "\n"
        + "要求：\n"
        + "· 直接把「要回给他的那句话」当作最终回答输出 —— **不要**调用任何发消息的工具（发送由外面代发）。\n"
        + "· 纯文本、不超过 200 字、像聊天。不要 markdown 星号/加粗，不要括号里写「（多少字…可继续发送…）」这类说明，不要复述这些要求。\n"
        + "· 需要的话可以先用 bili_search / bili_subtitle 查一下再答；拿不准就说没查到，别编。"
    )


def chat_history(n: int = 5) -> list[dict]:
    if not CHATLOG.exists():
        return []
    rows = []
    try:
        for line in CHATLOG.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        return []
    return rows[-n:]


def append_chat(user: str, bot: str) -> None:
    try:
        with CHATLOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"at": now_bj().isoformat(timespec="seconds"),
                                "user": user, "bot": bot}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def clean_reply(raw: str) -> str:
    """从 dsh 的输出里把最终那句话抠出来"""
    lines = []
    for line in (raw or "").splitlines():
        s = line.rstrip()
        if not s.strip():
            if lines:
                lines.append("")
            continue
        if s.lstrip().startswith(("dsh:", "Processing request", "INFO", "WARN", "DEBUG")):
            continue
        lines.append(s)
    text = "\n".join(lines).strip()
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)          # 去加粗
    text = re.sub(r"^```.*?$|^```$", "", text, flags=re.M).strip()
    if len(text) >= 2 and text[0] in "「\"'“" and text[-1] in "」\"'”":
        text = text[1:-1].strip()
    return text.strip()


def duty_busy() -> bool:
    """值班轮（刷视频）是否正在跑 —— 在跑就别抢 B站 请求，免得两边一起拖死。
    run-lock.json 由插件写：{pid, ts}；跑完会把它写成 pid=0。
    ⚠️ 别用"文件刚写过"当判据：跑完那一刻文件也是刚写过的，
       会把刚结束的一轮误判成"还在跑"（最多误 3 分钟）✗"""
    p = DUTY / "run-lock.json"
    try:
        if not p.exists():
            return False
        import time as _t
        if _t.time() - p.stat().st_mtime > 1800:      # 半小时前的锁一定是残留
            return False
        try:
            d = json.loads(p.read_text(encoding="utf-8") or "{}")
        except Exception:
            return False
        return int(d.get("pid") or 0) > 0
    except Exception:
        return False


def run_chat(text: str) -> str:
    if not pathlib.Path(NODE).exists() or not pathlib.Path(DSH_BIN).exists():
        return ""
    overlay = ensure_chat_overlay()
    cmd = [NODE, DSH_BIN, "--profile", "bili-duty", "--patch", str(overlay), chat_prompt(text)]
    r = run_proc(cmd, cwd=str(DUTY), timeout=300)
    return clean_reply(r.stdout or "")


# ── 私信收发 ──────────────────────────────────────────────────────────────
def load_cred_dict() -> dict:
    p = DUTY / "bili_credential.json"
    d = read_json(p, {}) or {}
    return {
        "sessdata": str(d.get("sessdata") or ""),
        "bili_jct": str(d.get("bili_jct") or ""),
        "buvid3": str(d.get("buvid3") or ""),
        "dedeuserid": str(d.get("dedeuserid") or ""),
    }


UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


async def fetch_msgs(size: int = 20) -> list[dict]:
    import aiohttp

    cred = load_cred_dict()
    url = ("https://api.vc.bilibili.com/svr_sync/v1/svr_sync/fetch_session_msgs"
           f"?talker_id={OWNER}&session_type=1&size={size}&build=0&mobi_app=web")
    # ⚠️ 必须照插件 lib/dm.mjs 那套头打：少 UA / Referer 会返回非 JSON（实测 2026-11-05）
    headers = {
        "User-Agent": UA,
        "Referer": "https://message.bilibili.com/",
        "Origin": "https://message.bilibili.com",
        "Cookie": f"SESSDATA={cred['sessdata']}; bili_jct={cred['bili_jct']}; buvid3={cred['buvid3']}",
    }
    timeout = aiohttp.ClientTimeout(total=20)
    async with aiohttp.ClientSession(timeout=timeout) as s:
        async with s.get(url, headers=headers) as resp:
            raw = await resp.text()
            try:
                data = json.loads(raw)
            except Exception:
                raise RuntimeError(f"读私信返回的不是 JSON（HTTP {resp.status}）：{raw[:160]!r}")
    if int(data.get("code") or 0) != 0:
        raise RuntimeError(f"fetch_session_msgs code={data.get('code')} {data.get('message')}")
    msgs = (data.get("data") or {}).get("messages") or []
    out = []
    for m in msgs:
        raw = m.get("content") or ""
        text = raw
        try:
            obj = json.loads(raw)
            text = str(obj.get("content") or obj.get("text") or "")
        except Exception:
            pass
        out.append({
            "key": str(m.get("msg_key") or m.get("timestamp")),
            "ts": int(m.get("timestamp") or 0),
            "from_me": str(m.get("sender_uid")) == cred["dedeuserid"],
            "text": text,
        })
    out.sort(key=lambda x: x["ts"])           # 旧 → 新
    return out


async def send_dm(text: str) -> None:
    from bilibili_api import Credential, session as bili_session

    c = load_cred_dict()
    cred = Credential(sessdata=c["sessdata"], bili_jct=c["bili_jct"],
                      buvid3=c["buvid3"], dedeuserid=c["dedeuserid"])
    await bili_session.send_msg(credential=cred, receiver_id=OWNER,
                               msg_type=bili_session.EventType.TEXT, content=text)


def chunk(text: str) -> list[str]:
    """按 480 字切段（尽量在换行处切），最多 4 段"""
    text = text.strip()
    parts, cur = [], ""
    for line in text.splitlines(True):
        while len(line) > DM_LIMIT:                     # 单行超长就硬切
            room = DM_LIMIT - len(cur)
            if room > 0:
                cur += line[:room]
                line = line[room:]
            parts.append(cur)
            cur = ""
        if len(cur) + len(line) > DM_LIMIT:
            parts.append(cur)
            cur = line
        else:
            cur += line
    if cur:
        parts.append(cur)
    if len(parts) > MAX_CHUNKS:
        parts = parts[:MAX_CHUNKS]
        parts[-1] = parts[-1][: DM_LIMIT - 20] + "\n…（后面截掉了）"
    return [p.strip() for p in parts if p.strip()]


# ── 命令解析 ──────────────────────────────────────────────────────────────
CMD_RE = re.compile(r"^\s*[/／#]\s*([a-zA-Z\u4e00-\u9fa5]+)\s*(.*)$", re.S)


def parse_command(text: str):
    m = CMD_RE.match(text or "")
    if not m:
        return None
    name = m.group(1).lower()
    rest = m.group(2).strip()
    if name not in cmds():
        if name in ("h", "?", "commands"):
            name = "help"
        else:
            return ("ERR", [name])
    return (name, rest.split())


# ── 主流程 ────────────────────────────────────────────────────────────────
async def run(dry: bool, simulate: str | None) -> None:
    if simulate is not None:
        cmd = parse_command(simulate)
        if not cmd:
            print("（不是命令）")
            return
        if cmd[0] == "ERR":
            reply = f"没有这个命令：/{cmd[1][0]}　发 /help 看看有哪些。"
        else:
            reply = cmds()[cmd[0]](cmd[1])
        parts = chunk(reply)
        for i, p in enumerate(parts, 1):
            print(f"\n───── 第 {i}/{len(parts)} 条（{len(p)} 字）─────\n{p}")
        return

    st = read_json(STATE, {"lastTs": 0, "handled": []}) or {"lastTs": 0, "handled": []}
    handled = set(st.get("handled") or [])
    last_ts = int(st.get("lastTs") or 0)

    msgs = await fetch_msgs(20)
    # ⭐ 心跳：只要**成功拉到私信**就记一次 —— /status 的新鲜度、托盘的存活判断、
    #    以及"进程是不是静默死了"都靠这个时间戳（2026-11-05 ①③）
    if not dry:
        hb = read_json(STATE, {}) or {}
        hb["lastScan"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        hb["scans"] = int(hb.get("scans") or 0) + 1
        write_json(STATE, hb)
    incoming = [m for m in msgs if not m["from_me"]]
    if not incoming:
        if not dry:
            print("没有新消息。")
        return

    newest = max(m["ts"] for m in incoming)
    fresh = [m for m in incoming if m["ts"] > last_ts and m["key"] not in handled]

    # ⭐ 每次扫都顺手对一次账（报告 vs 判重表）—— 纯读文件，没缺口就零成本
    if RECONCILE.exists() and not dry:
        try:
            r = run_proc([NODE, str(RECONCILE)], timeout=180)
            out = (r.stdout or "").strip()
            if out and "一致，没有要补的" not in out:
                append_log("对账：" + out.replace("\n", " / ")[:200])
        except Exception as e:
            append_log(f"对账跑挂：{e}")

    # ⭐ 把「你设的规矩 + 你回过的判据」渲染进章程 —— 让追问的效果真的传到下一轮
    #   （2026-11-05：以前标签只写进 判据统计.json，没有任何东西读它 ⇒ 表现成"我回了但没变化"）
    if PREF.exists() and not dry:
        try:
            run_proc([NODE, str(PREF)], timeout=120)
        except Exception as e:
            append_log(f"偏好刷新跑挂：{e}")

    # 有新消息 ⇒ 顺便跑一次评分（这样纯文字评价也能马上进缓冲区）
    if fresh and SCORING.exists() and not dry:
        # ⭐ 先算出「哪条消息是用来回答追问的」——告诉 评分.mjs 别把它当评价记账。
        #    它以**第一条**能解析成回答的消息为准（跟下面循环里的消费顺序一致）。
        skip_keys: list[str] = []
        qa_pre = read_ask()
        if qa_pre and qa_pre.get("asked"):
            for mm in fresh:
                if parse_ask_answer(mm["text"], qa_pre):
                    skip_keys.append(mm["key"])
                    break
        try:
            r = run_proc([os.environ.get("BILI_NODE") or "node", str(SCORING)], timeout=180,
                         env={**os.environ, "BILI_SKIP_MSG_KEYS": ",".join(skip_keys)})
            # ⭐ 文字评价/打分不再静默：让评分脚本的结果回给使用者
            fb_msg = format_feedback(parse_feedback(r.stdout or ""))
            if fb_msg:
                for part in chunk(fb_msg):
                    if dry:
                        print("---- 回执预览 ----\n" + part)
                    else:
                        await send_dm(part)
                        await asyncio.sleep(1.0)
                append_log("回执：" + fb_msg[:80])
        except Exception as e:
            print("评分脚本跑挂了（忽略）：", e)

    # ⭐ 有挂起的追问就先问出去（一次只挂一个，问过就标 asked）
    q0 = read_ask()
    if q0 and not q0.get("asked"):
        body = format_ask(q0)
        if body:
            for p in chunk(body):
                if dry:
                    print("---- 追问预览 ----\n" + p)
                else:
                    await send_dm(p)
                    await asyncio.sleep(1.0)
            if not dry:
                q0["asked"] = True
                q0["askedAt"] = now_bj().isoformat(timespec="seconds")
                write_ask(q0)
                append_log(f"发出追问：{q0.get('bvid')}")
            print(f"[追问] {q0.get('bvid')} 已发出")

    for m in fresh:
        # ⭐⭐ 指令优先级最高：加词 / 删词（2026-11-06 加 —— 以前这类消息会掉进
        #   "文字评价"被静默记账：词没加、追问没关、一个字都不回）
        if parse_kw_command(m["text"]):
            reply = handle_kw_command(m["text"], dry)
            print(f"[{m['ts']}] 关键词指令 → {reply.replace(chr(10), ' ')[:40]}")
            for p in chunk(reply):
                if dry:
                    print("---- 预览 ----\n" + p)
                else:
                    await send_dm(p)
                    await asyncio.sleep(1.0)
            handled.add(m["key"])
            continue

        # ⭐ 再看是不是在回答追问（裸数字只在「已经问出去」时才当答案）
        qa = read_ask()
        explicit = m["text"].lstrip().startswith(("/答", "/answer"))
        if explicit and not qa:
            reply = "现在没有要回答的问题。打分直接发 `1=10 3=9` 就行。"
        elif qa and (explicit or qa.get("asked")):
            ans = parse_ask_answer(m["text"], qa)
            reply = record_ask_answer(qa, ans[0], ans[1], dry) if ans else None
        else:
            reply = None
        if reply is not None:
            print(f"[{m['ts']}] 追问回答 → {reply.replace(chr(10), ' ')[:40]}")
            for p in chunk(reply):
                if dry:
                    print("---- 预览 ----\n" + p)
                else:
                    await send_dm(p)
                    await asyncio.sleep(1.0)
            handled.add(m["key"])
            continue

        cmd = parse_command(m["text"])
        if not cmd:
            # 不是命令 ⇒ 评价就静静记账（评分.mjs 已经跑过），其余当**简化版对话**回一句
            if looks_like_review(m["text"]):
                append_log(f"评价（不回话）：{m['text'][:40]}")
                handled.add(m["key"])
                continue
            append_log(f"对话：{m['text'][:60]}")
            if duty_busy():
                reply = "我正刷着B站呢，等这一轮跑完再答你（也就几分钟）。"
                append_log("对话让路：值班轮在跑")
            else:
                try:
                    reply = run_chat(m["text"])
                except Exception as e:
                    reply = ""
                    append_log(f"对话跑挂：{e}")
            if not reply:
                reply = "刚去找了一圈没接上话，等会儿再发我一次？"
            parts = chunk(reply)
            print(f"[{m['ts']}] 对话 → {len(parts)} 条回复")
            for p in parts:
                if dry:
                    print("---- 预览 ----\n" + p)
                else:
                    await send_dm(p)
                    await asyncio.sleep(1.0)
            if not dry:
                append_chat(m["text"], reply)
            handled.add(m["key"])
            continue
        if cmd[0] == "ERR":
            reply = f"没有这个命令：/{cmd[1][0]}　发 /help 看看有哪些。"
        else:
            try:
                reply = cmds()[cmd[0]](cmd[1])
            except Exception as e:
                reply = f"/{cmd[0]} 执行失败：{e}"
        parts = chunk(reply)
        print(f"[{m['ts']}] 命令 /{cmd[0] if cmd[0] != 'ERR' else cmd[1][0]} → {len(parts)} 条回复")
        append_log(f"命令 /{cmd[0] if cmd[0] != 'ERR' else cmd[1][0]} → {len(parts)} 条回复")
        for p in parts:
            if dry:
                print("---- 预览 ----\n" + p)
            else:
                await send_dm(p)
                await asyncio.sleep(1.0)              # 连发要慢一点，免得被风控
        handled.add(m["key"])

    if not dry:
        merged = read_json(STATE, {}) or {}
        merged["lastTs"] = max(last_ts, newest)
        merged["lastScan"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        merged["handled"] = list(handled)[-200:]
        write_json(STATE, merged)


def main() -> None:
    dry = "--dry" in sys.argv
    sim = None
    if "--simulate" in sys.argv:
        global SIMULATE
        SIMULATE = True            # 预览模式：只读，不落盘
        i = sys.argv.index("--simulate")
        sim = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    if "--simulate-chat" in sys.argv:
        i = sys.argv.index("--simulate-chat")
        text = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        if not text.strip():
            print("用法：--simulate-chat \"今天有什么好看的\"")
            return
        print(f"[会不会被当成评价] {looks_like_review(text)}")
        reply = run_chat(text)
        parts = chunk(reply or "（空）")
        for n, p in enumerate(parts, 1):
            print(f"\n───── 第 {n}/{len(parts)} 条（{len(p)} 字）─────\n{p}")
        return
    if "--send" in sys.argv:
        i = sys.argv.index("--send")
        text = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
        if not text.strip():
            print("用法：--send \"要发的内容\"")
            return
        for p in chunk(text):
            asyncio.run(send_dm(p))
            print("已发送：", p[:40].replace("\n", " "))
            append_log(f"--send {p[:60]}")
        return
    # 计划任务里 stdout 是丢掉的 ⇒ 扫描失败必须自己留痕，否则风控/接口变了都发现不了
    if not acquire_lock():
        print("上一轮还在跑，本次跳过。")
        return
    try:
        asyncio.run(run(dry, sim))
        if not dry:                       # 成功 ⇒ 失败计数清零
            st = read_json(STATE, {}) or {}
            if st.get("failStreak") or st.get("failAlerted"):
                st["failStreak"] = 0
                st["failAlerted"] = False
                write_json(STATE, st)
    except Exception as e:
        import traceback
        detail = traceback.format_exc(limit=4).replace("\n", " ")[:400]
        print("扫描失败：", e)
        append_log(f"扫描失败：{e}｜{detail}")
        # ⭐ 连续失败 3 次就私信告警一次（凭据过期 / 风控，不然它静默死掉没人知道）
        if not dry:
            st = read_json(STATE, {}) or {}
            streak = int(st.get("failStreak") or 0) + 1
            st["failStreak"] = streak
            if streak >= 3 and not st.get("failAlerted"):
                try:
                    asyncio.run(send_dm(
                        f"【刷B站 · 控制台】私信扫不动了，已经连续失败 {streak} 次：{str(e)[:110]}\n"
                        "多半是登录过期或接口风控，重新扫码登录一下就好。"))
                    st["failAlerted"] = True
                    append_log("已发失败告警")
                except Exception as e2:
                    append_log(f"失败告警也发不出去：{e2}")
            write_json(STATE, st)
        raise SystemExit(1)
    finally:
        release_lock()


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except BaseException as _e:                     # pythonw 下没有 stderr，崩了也得留痕
        import traceback as _tb
        try:
            with (DUTY / "console.log").open("a", encoding="utf-8") as _f:
                _f.write("[" + now_bj().isoformat(timespec="seconds") + "] 控制台崩溃："
                         + str(_e) + "｜" + _tb.format_exc(limit=5).replace("\n", " ")[:600] + "\n")
        except Exception:
            pass
        raise SystemExit(1)
