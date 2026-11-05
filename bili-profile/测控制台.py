"""私信控制台 自测：只看纯函数，不碰网络、不发私信。"""
import importlib.util
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

print(f"\n通过 {ok} · 失败 {fail}")
if fail:
    sys.exit(1)
