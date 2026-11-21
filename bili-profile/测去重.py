"""去重闸自测：判重表 + 往期日报 + sent-bvids → 已推过的 BV → 剔行。

被测对象是 `patches/mcp_server/patched.py` 里的 `_delivered_bvids` / `_strip_duplicates` /
`_record_sent`（它们跑在 MCP 进程里，是发私信前的第三道闸）。用临时家目录，不碰真实数据。

⚠️ 2026-11-18 的两条关键规则（都踩过坑）：
   · **今天的**判重表/日报**不算**推过 —— 章程要求「报告 → 判重表 → 归档 → 私信」，
     模型写完报告再发私信时，闸门会读到自己刚写的记录，算进去就整条挡回；
   · 真正发成功过的记在 `sent-bvids.txt`（唯一可靠来源），今天发过的也要算。
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
os.environ["BILI_DUTY_HOME"] = str(tmp)

spec = importlib.util.spec_from_file_location("mcp_patched", SRC)
m = importlib.util.module_from_spec(spec)
sys.modules["mcp_patched"] = m
spec.loader.exec_module(m)

TODAY = m._duty_today_str()

(tmp / "seen.md").write_text(
    "# 判重表\n\n"
    "| 日期 | BV | 标题 | UP | 状态 |\n"
    "|---|---|---|---|---|\n"
    "| 2026-11-01 | BV1aaaaaaaaa | 老视频一 | UP | 挑了 |\n"
    "| 2026-11-02 | BV1bbbbbbbbb | 老视频二 | UP | 挑了 |\n"
    "| 2026-11-03 | BV1ccccccccc | 看过的 | UP | 跳过 |\n"
    f"| {TODAY} | BV1fffffffff | 本轮刚挑的 | UP | 挑了 |\n",
    encoding="utf-8")
(tmp / "out" / "2026-11-05.md").write_text(
    "# 日报\n\n### BV1ddddddddd\n《往期》\n\n### BV1eeeeeeeee\n另一条\n", encoding="utf-8")
(tmp / "out" / f"{TODAY}.md").write_text(
    f"# 日报\n\n### BV1ttttttttt\n本轮刚写进报告的\n", encoding="utf-8")
(tmp / "sent-bvids.txt").write_text("BV1ggggggggg\n", encoding="utf-8")

ok = fail = 0


def eq(name, got, want):
    global ok, fail
    good = got == want
    ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
    print(("✓ " if good else "✗ ") + name + ("" if good else f"\n    got {got!r}\n    want {want!r}"))


print("=== 1. 「已推过」的口径 ===")
delivered = m._delivered_bvids()
print("   判定为已推过:", sorted(delivered))
eq("历史判重表 挑了 的算", "BV1aaaaaaaaa" in delivered, True)
eq("历史判重表第二条也算", "BV1bbbbbbbbb" in delivered, True)
eq("判重表 跳过 的不算", "BV1ccccccccc" in delivered, False)
eq("历史日报 ### 行算", "BV1ddddddddd" in delivered, True)
eq("sent-bvids 里的算（今天发过的也拦）", "BV1ggggggggg" in delivered, True)
eq("⛔ 今天的判重表「挑了」不算（否则挡回自己）", "BV1fffffffff" in delivered, False)
eq("⛔ 今天的日报 ### 不算（同上）", "BV1ttttttttt" in delivered, False)
eq("一共 5 条（2 历史挑了 + 2 历史日报 + 1 sent）", len(delivered), 5)

print("\n=== 2. 剔行 ===")
text = "[1] 老视频一 BV1aaaaaaaaa —— 理由\n[2] 全新视频 BV1zzzzzzzzz —— 理由"
new, dropped = m._strip_duplicates(text)
eq("剔掉了旧的", dropped, ["BV1aaaaaaaaa"])
eq("新的还在", "BV1zzzzzzzzz" in new, True)
eq("旧的那行没了", "BV1aaaaaaaaa" not in new, True)

print("\n=== 3. 本轮刚写进报告的不该被拦 ===")
t_fresh = "[1] 本轮刚挑的 BV1fffffffff\n[2] 本轮刚写的 BV1ttttttttt"
eq("今天的记录不拦", m._strip_duplicates(t_fresh), (t_fresh, []))

print("\n=== 4. 全重复 ⇒ 剔完没 BV ===")
new2, dropped2 = m._strip_duplicates("[1] 老一 BV1aaaaaaaaa\n[2] 老二 BV1bbbbbbbbb")
eq("两条都被剔", sorted(dropped2), ["BV1aaaaaaaaa", "BV1bbbbbbbbb"])
eq("剔完没有 BV 了", m._BV_RE.search(new2) is None, True)

print("\n=== 5. 同一条私信内部重复 ===")
new3, dropped3 = m._strip_duplicates("[1] 新 BV1zzzzzzzzz\n[2] 同一个 BV1zzzzzzzzz 又写一遍")
eq("内部重复剔掉一条", dropped3, ["BV1zzzzzzzzz"])
eq("第一次出现的保留", new3.count("BV1zzzzzzzzz"), 1)

print("\n=== 6. 发送后记账 ===")
m._record_sent("[1] 视频甲 BV1kkkkkkkkk\n[2] 视频乙 BV1mmmmmmmmm")
saved = (tmp / "sent-bvids.txt").read_text(encoding="utf-8").split()
eq("两个都记下了", sorted(x for x in saved if x in ("BV1kkkkkkkkk", "BV1mmmmmmmmm")),
   ["BV1kkkkkkkkk", "BV1mmmmmmmmm"])
eq("记完立刻算「推过」", "BV1kkkkkkkkk" in m._delivered_bvids(), True)
m._record_sent("[1] 视频甲 BV1kkkkkkkkk")
saved2 = (tmp / "sent-bvids.txt").read_text(encoding="utf-8").split()
eq("重复调不重复记（同一私信内去重）", saved2.count("BV1kkkkkkkkk"), 2)

print("\n=== 7. 不该误伤的 ===")
t4 = "[1] 看过的那个 BV1ccccccccc"
eq("「跳过」过的还能推", m._strip_duplicates(t4), (t4, []))
t5 = "今天没有值得看的，休息一下。"
eq("纯文字私信原样返回", m._strip_duplicates(t5), (t5, []))

print("\n=== 8. 链接完整性（2026-11-20 截图反馈：有的条目没链接）===")
OK_TEXT = ("[1] 标题甲\n"
           "https://www.bilibili.com/video/BV1aaaaaaaaa · 理由\n"
           "[2] 标题乙\n"
           "https://www.bilibili.com/video/BV1zzzzzzzzz · 理由")
eq("每条都有链接 → 不报缺", m._items_missing_link(OK_TEXT), [])
BAD_TEXT = ("[1] 标题甲\n"
            "https://www.bilibili.com/video/BV1aaaaaaaaa · 理由\n"
            "[2] 标题乙\n"
            "只有理由没链接\n"
            "[3] 标题丙\n"
            "BV1zzzzzzzzz · 理由")
eq("缺链接的第 2 条被揪出来", m._items_missing_link(BAD_TEXT), [2])
eq("BV 号也算链接", m._items_missing_link("[1] x\nBV1zzzzzzzzz · 理由"), [])
eq("光有标题没链接", m._items_missing_link("[1] 只有标题"), [1])
eq("编号重复也能各自校验", m._items_missing_link("[3] a\nBV1zzzzzzzzz\n[3] b"), [3])

print(f"\n通过 {ok} · 失败 {fail}")
if fail:
    sys.exit(1)
