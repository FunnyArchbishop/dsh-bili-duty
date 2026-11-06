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

print(f"\n通过 {ok} · 失败 {fail}")
if fail:
    sys.exit(1)
