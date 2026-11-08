"""去重闸自测：判重表 + 往期日报 → 已推过的 BV → 剔行。

被测对象是 `patches/mcp_server/patched.py` 里的 `_delivered_bvids` / `_strip_duplicates`
（它们跑在 MCP 进程里，是发私信前的第三道闸）。这里用临时家目录，不碰真实数据。
"""
import importlib.util
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "patches" / "mcp_server" / "patched.py"
assert SRC.exists(), f"找不到 {SRC}"

tmp = pathlib.Path(tempfile.mkdtemp(prefix="bili-dedup-"))
(tmp / "out").mkdir()
# 注意格式：行以 | 开头 ⇒ split('|') 后 parts[0] 是空串，BV 在 parts[2]
(tmp / "seen.md").write_text(
    "# 判重表\n\n"
    "| 日期 | BV | 标题 | UP | 状态 |\n"
    "|---|---|---|---|---|\n"
    "| 2026-11-01 | BV1aaaaaaaaa | 老视频一 | UP | 挑了 |\n"
    "| 2026-11-02 | BV1bbbbbbbbb | 老视频二 | UP | 挑了 |\n"
    "| 2026-11-03 | BV1ccccccccc | 看过的 | UP | 跳过 |\n",
    encoding="utf-8")
(tmp / "out" / "2026-11-05.md").write_text(
    "# 日报\n\n### BV1ddddddddd\n《往期日报里的那条》\n\n### BV1eeeeeeeee\n另一条\n",
    encoding="utf-8")
os.environ["BILI_DUTY_HOME"] = str(tmp)

spec = importlib.util.spec_from_file_location("mcp_patched", SRC)
m = importlib.util.module_from_spec(spec)
sys.modules["mcp_patched"] = m
spec.loader.exec_module(m)

ok = fail = 0


def eq(name, got, want):
    global ok, fail
    good = got == want
    ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
    print(("✓ " if good else "✗ ") + name + ("" if good else f"\n    got {got!r}\n    want {want!r}"))


print("=== 1. 「已推过」的口径 ===")
delivered = m._delivered_bvids()
print("   判定为已推过:", sorted(delivered))
eq("判重表里 挑了 的算推过", "BV1aaaaaaaaa" in delivered, True)
eq("第二条挑了也算", "BV1bbbbbbbbb" in delivered, True)
eq("判重表里 跳过 的不算推过", "BV1ccccccccc" in delivered, False)
eq("往期日报 ### 行算推过", "BV1ddddddddd" in delivered, True)
eq("往期日报第二条也算", "BV1eeeeeeeee" in delivered, True)
eq("一共 4 条", len(delivered), 4)

print("\n=== 2. 剔行 ===")
text = "[1] 老视频一 BV1aaaaaaaaa —— 理由\n[2] 全新视频 BV1zzzzzzzzz —— 理由"
new, dropped = m._strip_duplicates(text)
eq("剔掉了旧的", dropped, ["BV1aaaaaaaaa"])
eq("新的还在", "BV1zzzzzzzzz" in new, True)
eq("旧的那行没了", "BV1aaaaaaaaa" not in new, True)

print("\n=== 3. 全重复 ⇒ 剔完没 BV（上层会整条拒发）===")
new2, dropped2 = m._strip_duplicates("[1] 老视频一 BV1aaaaaaaaa\n[2] 老视频二 BV1bbbbbbbbb")
eq("两条都被剔", sorted(dropped2), ["BV1aaaaaaaaa", "BV1bbbbbbbbb"])
eq("剔完没有 BV 了", m._BV_RE.search(new2) is None, True)

print("\n=== 4. 同一条私信内部重复 ===")
new3, dropped3 = m._strip_duplicates("[1] 新视频 BV1zzzzzzzzz\n[2] 同一个 BV1zzzzzzzzz 又写了一遍")
eq("内部重复剔掉一条", dropped3, ["BV1zzzzzzzzz"])
eq("第一次出现的保留", new3.count("BV1zzzzzzzzz"), 1)

print("\n=== 5. 不该误伤的 ===")
t4 = "[1] 看过的那个 BV1ccccccccc"
eq("「跳过」过的还能推", m._strip_duplicates(t4), (t4, []))
t5 = "今天没有值得看的，休息一下。"
eq("纯文字私信原样返回", m._strip_duplicates(t5), (t5, []))
t6 = "[1] 全新 BV1yyyyyyyyy\n[2] 全新 BV1xxxxxxxxx"
eq("全都没推过 → 原样", m._strip_duplicates(t6), (t6, []))

print(f"\n通过 {ok} · 失败 {fail}")
if fail:
    sys.exit(1)
