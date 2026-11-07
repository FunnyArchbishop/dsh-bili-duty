"""私信控制台 自测：只看纯函数，不碰网络、不发私信。"""
import importlib.util
import json
import pathlib
import sys

SRC = pathlib.Path(__file__).resolve().parent / "私信控制台.py"
spec = importlib.util.spec_from_file_location("c", SRC)
m = importlib.util.module_from_spec(spec)
sys.modules["c"] = m
spec.loader.exec_module(m)

ok = fail = 0


def eq(name, got, want):
    global ok, fail
    good = got == want
    ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
    print(("✓ " if good else "✗ ") + name + ("" if good else f"\n    got {got!r}\n    want {want!r}"))


# ── 1. 评价 vs 对话（含全角）────────────────────────────────────────────
for t in ["1=10 3=9", "3＝11 有深度", "１＝１０", "5＝-1 标题党", "4 调色板真舒服", "2=11 空岛讲得清楚"]:
    eq(f"算评价：{t}", m.looks_like_review(t), True)
for t in ["今天有什么好看的", "帮我找点东方的", "这条泰拉瑞亚的电路讲得真好"]:
    eq(f"算对话：{t}", m.looks_like_review(t), False)

# ── 2. 值班轮让路锁 ────────────────────────────────────────────────────
lock = m.DUTY / "run-lock.json"
backup = lock.read_text(encoding="utf-8") if lock.exists() else None
try:
    lock.write_text('{"pid": 99999, "ts": 0}', encoding="utf-8")
    eq("pid>0 ⇒ 认为在跑", m.duty_busy(), True)
    lock.write_text('{"pid": 0, "ts": 0}', encoding="utf-8")
    eq("pid=0 ⇒ 认为没跑", m.duty_busy(), False)
    lock.write_text("这不是 json", encoding="utf-8")
    eq("坏锁 ⇒ fail-safe 不阻塞", m.duty_busy(), False)
    lock.unlink()
    eq("没有锁文件 ⇒ 没跑", m.duty_busy(), False)
finally:
    lock.write_text(backup if backup is not None else '{"pid": 0, "ts": 0}', encoding="utf-8")

# ── 3. 私信切段 ────────────────────────────────────────────────────────
long = "\n".join(f"[{i}] 视频标题第 {i} 条 https://b23.tv/BV1xxxxxxxxx · 一句话理由写这里" for i in range(1, 15))
parts = m.chunk(long)
eq("切段后每段都 ≤ 上限", all(len(p) <= m.DM_LIMIT for p in parts), True)
eq("切段不超过 4 条", len(parts) <= m.MAX_CHUNKS, True)
eq("空串切出 0 段", m.chunk("   "), [])

# ── 4. 命令解析 ────────────────────────────────────────────────────────
eq("解析 /kw add 钢琴", m.parse_command("/kw add 钢琴"), ("kw", ["add", "钢琴"]))
eq("全角斜杠也认", m.parse_command("／debug"), ("debug", []))
eq("不认识的命令", m.parse_command("/wat")[0], "ERR")
eq("不是命令", m.parse_command("1=10"), None)

# ── 5. 私信里的「加词/删词」指令（2026-11-06：以前会被当成文字评价静默吞掉）──
eq("带条目号 + 全角冒号", m.parse_kw_command("4 · 加词：可玩性强"), ("add", ["可玩性强"]))
eq("不带条目号", m.parse_kw_command("加词：可玩性强"), ("add", ["可玩性强"]))
eq("空格分隔", m.parse_kw_command("4 加词 可玩性强"), ("add", ["可玩性强"]))
eq("全角空格", m.parse_kw_command("加词　可玩性强"), ("add", ["可玩性强"]))
eq("多个词", m.parse_kw_command("加关键词:东方 音乐"), ("add", ["东方", "音乐"]))
eq("删词", m.parse_kw_command("3、删词：高数"), ("del", ["高数"]))
eq("删掉也认", m.parse_kw_command("删掉关键词：高数"), ("del", ["高数"]))
eq("打分不能被当成指令", m.parse_kw_command("4＝11"), None)
eq("普通评价不是指令", m.parse_kw_command("4 调色板真舒服"), None)
eq("闲聊不是指令", m.parse_kw_command("今天有什么好看的"), None)
eq("单字词被丢掉", m.parse_kw_command("加词：好"), None)

# ── 6. 文字评价的「检查→反馈」链（2026-11-06）──────────────────────────
STDOUT = """已记账 3 条到 ratings.jsonl
__FEEDBACK__ {"rows":3,"scores":[{"bvid":"BV1a","score":11,"note":"私信"},{"bvid":"BV1b","score":10,"note":"私信"}],"texts":[{"bvid":"BV1c","note":"可玩性强"}],"asks":1,"added":["可玩性强"],"removed":[]}
"""
fb = m.parse_feedback(STDOUT)
eq("能抠出机器行", (fb or {}).get("rows"), 3)
eq("没有机器行时返回 None", m.parse_feedback("只有人话"), None)
msg = m.format_feedback(fb)
print("   回执长这样：", msg)
eq("回执提到打分条数", "记下 2 条打分" in msg, True)
eq("回执提到文字评价", "文字评价" in msg, True)
eq("回执提到加词", "关键词 +可玩性强" in msg, True)
eq("回执提到要追问", "追问你" in msg, True)
eq("空 payload 不回执", m.format_feedback({}), "")

print("\n=== 7. /查 预检只看不动 ===")
before_cfg = json.loads(pathlib.Path(m.CFG).read_text(encoding="utf-8"))
r1 = m.cmd_check(["4", "加词：可玩性强"])
eq("预检认出加词指令", "关键词指令" in r1, True)
eq("预检标明什么都没改", "什么都没改" in r1, True)
r2 = m.cmd_check(["4", "讲得真清楚"])
eq("预检认出文字评价", "文字评价" in r2, True)
r3 = m.cmd_check(["1=10", "3=9"])
eq("预检认岀打分", "打分" in r3, True)
r4 = m.cmd_check(["今天有什么好看的"])
eq("预检认出闲聊", "聊天" in r4, True)
eq("预检确实没改配置",
   json.loads(pathlib.Path(m.CFG).read_text(encoding="utf-8")), before_cfg)

print("\n=== 8. /give 立刻刷一轮 ===")
#  ⚠️ 全部走 SIMULATE（预览），绝不真的起轮子 —— 起一轮要烧钱几分钟
m.SIMULATE = True
g = m.cmd_give(["5"])
eq("give 5 走预览不起进程", "预览模式" in g, True)
eq("give 5 说的是 5 条", "挑 5 条" in g, True)
eq("give 没给数字 → 用法", "用法" in m.cmd_give([]), True)
eq("give abc → 用法", "用法" in m.cmd_give(["abc"]), True)
eq("give 0 → 用法", "用法" in m.cmd_give(["0"]), True)
eq("give 99 → 夹到上限 10", "挑 10 条" in m.cmd_give(["99"]), True)
eq("give 上限常量", m.GIVE_MAX, 10)
eq("give 冷却常量", m.GIVE_COOLDOWN_MIN, 5)
eq("give 已注册", "give" in m.cmds(), True)
eq("help 里有 give", "/give" in m.cmd_help([]), True)

# 提示词本身：必须内联章程（那一轮没有文件系统、读不到 duty.md）、且塞得进命令行
_pr = m.build_give_prompt(3)
eq("提示词写着只挑 3 条", "只挑 3 条" in _pr, True)
eq("提示词写着手动触发", "手动触发" in _pr, True)
eq("提示词要求 ### BV 行", "### BV" in _pr, True)
eq("提示词内联了章程（不是只给路径）", "值班章程" in _pr and len(_pr) > 5000, True)
eq("提示词长度塞得进 Windows 命令行", len(_pr) < 32000, True)
print(f"   build_give_prompt(3) = {len(_pr)} 字符")

# 冷却：写进 lastGiveAt 之后就该被挡住
_st = json.loads(pathlib.Path(m.STATE).read_text(encoding="utf-8")) if pathlib.Path(m.STATE).exists() else {}
_keep = dict(_st)
try:
    _st["lastGiveAt"] = m.now_bj().timestamp()
    pathlib.Path(m.STATE).write_text(json.dumps(_st), encoding="utf-8")
    eq("冷却期内拒绝", "刚给过一轮" in m.cmd_give(["3"]), True)
finally:
    pathlib.Path(m.STATE).write_text(json.dumps(_keep), encoding="utf-8")
m.SIMULATE = False

print("\n=== 9. /help 版式 ===")
_h = m.cmd_help([])


def _disp(s):
    return sum(2 if ord(c) > 0x2E80 else 1 for c in s)


eq("help 不带星号（私信不是 markdown）", "**" not in _h, True)
eq("help 塞得进一条私信（≤460 字）", len(_h) <= 460, True)
eq("help 只分 1 片", len(m.chunk(_h)), 1)
_eq_w = max(_disp(ln) for ln in _h.splitlines())
eq("最宽一行 ≤ 26", _eq_w <= 26, True)
print("   字符数:", len(_h), "｜最宽行宽:", _eq_w)
for _cmd in ("/kw add", "/kw del", "/mute", "/unmute", "/ban", "/gate", "/learn",
             "/debug", "/status", "/last", "/list", "/buf", "/cost", "/答",
             "/give", "/查", "/help"):
    eq(f"help 列了 {_cmd}", _cmd in _h, True)

print("\n=== 10. 定时投递（11:30 / 21:30）===")
import datetime as _dt

_BJ = _dt.timezone(_dt.timedelta(hours=8))


def _at(h, mi):
    return _dt.datetime(2026, 11, 7, h, mi, tzinfo=_BJ)


eq("两个时间点", m.AUTO_SEND_TIMES, ["11:30", "21:30"])
eq("每次条数", m.AUTO_SEND_PER, 8)
eq("11:29 还没到", m._auto_send_due(_at(11, 29), []), None)
eq("11:30 到点", m._auto_send_due(_at(11, 30), []), "11:30")
eq("12:59 仍在宽限内（休眠回来赶得上）", m._auto_send_due(_at(12, 59), []), "11:30")
eq("13:00 过了宽限就不补", m._auto_send_due(_at(13, 0), []), None)
eq("已发过就不再发", m._auto_send_due(_at(11, 30), ["11:30"]), None)
eq("21:30 到点", m._auto_send_due(_at(21, 30), ["11:30"]), "21:30")
eq("22:59 宽限内", m._auto_send_due(_at(22, 59), ["11:30"]), "21:30")
eq("23:01 过了", m._auto_send_due(_at(23, 1), ["11:30"]), None)
eq("两个都发过 → 不再发", m._auto_send_due(_at(21, 40), ["11:30", "21:30"]), None)

print(f"\n通过 {ok} · 失败 {fail}")
if fail:
    sys.exit(1)
