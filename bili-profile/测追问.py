"""追问闭环自测：只测纯函数，不写真实数据（record 全走 dry=True）。"""
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


Q = {"tags": ["有考据", "讲得清楚", "选题妙", "制作精良"],
     "words": ["儿童漫画", "艺术家", "泡水灵梦"],
     "kind": "good", "score": 11, "title": "儿童漫画家杀死角色？艺术家能摆脱政治立场吗",
     "bvid": "BV1SoxT6qEEb"}

print("=== ① 答案解析 ===")
eq("裸数字", m.parse_ask_answer("1 3", Q), ("nums", [1, 3]))
eq("顿号/逗号混写", m.parse_ask_answer("1、3，5", Q), ("nums", [1, 3, 5]))
eq("中文数字分隔符", m.parse_ask_answer("2＋6", Q), ("nums", [2, 6]))
eq("/答 前缀", m.parse_ask_answer("/答 2 5", Q), ("nums", [2, 5]))
eq("全角数字", m.parse_ask_answer("１ ３", Q), ("nums", [1, 3]))
eq("自由文本", m.parse_ask_answer("考据扎实，讲得透", Q), ("text", "考据扎实，讲得透"))

print("\n=== ② 打分必须原样放行（不能被当成回答吞掉）===")
eq("打分 1=10 3=9", m.parse_ask_answer("1=10 3=9", Q), None)
eq("全角打分 3＝11", m.parse_ask_answer("3＝11 有深度", Q), None)
eq("文字评价 4 调色板真舒服", m.parse_ask_answer("4 调色板真舒服", Q), None)

print("\n=== ③ 选项文案 ===")
body = m.format_ask(Q)
print("   ----")
for line in body.splitlines():
    print("   " + line)
print("   ----")
eq("含两组选项", ("【怎么好】" in body) and ("【加哪个词】" in body), True)
eq("编号从 1 连续到 7", all(f"{i}" in body for i in range(1, 8)), True)
eq("带评分和标题", ("11 分" in body) and ("儿童漫画" in body), True)

print("\n=== ④ 记录（dry，不落盘）===")
r1 = m.record_ask_answer(dict(Q, answered=False), "nums", [1, 5], True)
print("   选 1+5 →", r1.replace("\n", " / "))
eq("选中判据 + 关键词", ("有考据" in r1) and ("儿童漫画" in r1), True)
r2 = m.record_ask_answer(dict(Q, answered=False), "nums", [99], True)
eq("越界编号会提示", "对不上" in r2, True)
r3 = m.record_ask_answer(dict(Q, answered=False), "text", "讲得清楚，有考据", True)
eq("自由文本走提炼", "收到" in r3, True)

print(f"\n通过 {ok} · 失败 {fail}")
if fail:
    sys.exit(1)
