"""投递闸门自测：闸门是纯判断，不值得为它发一条私信去验。

① _gate_one 的四种规则（词 / UP / 时长 / 播放量）+ 合集豁免
② _prefs 能读到 config.json 的 excludeWords 和 prefs.json
③ _delivery_check 对**真实 BV** 只读不写（默认规则全关时应该放行）
"""
import asyncio
import importlib.util
import json
import os
import pathlib
import sys

# 按 环境变量 > local.json > ~/.dsh/bili-duty 定位（不写死本机路径）
LOCAL = {}
try:
    LOCAL = json.loads((pathlib.Path(__file__).resolve().parent / "local.json").read_text(encoding="utf-8"))
except Exception:
    pass
DUTY = pathlib.Path(os.environ.get("BILI_DUTY_HOME") or LOCAL.get("dutyHome")
                    or (pathlib.Path.home() / ".dsh" / "bili-duty"))

SRC = DUTY / "mcp_server.py"
spec = importlib.util.spec_from_file_location("bili_mcp", SRC)
m = importlib.util.module_from_spec(spec)
sys.modules["bili_mcp"] = m
spec.loader.exec_module(m)

ok = fail = 0


def eq(name, got, want):
    global ok, fail
    good = got == want
    ok, fail = (ok + 1, fail) if good else (ok, fail + 1)
    print(("✓ " if good else "✗ ") + name + ("" if good else f"\n    got {got!r}\n    want {want!r}"))


META = {"title": "【泰拉瑞亚】32位计算机电路 RISC-V CPU 348KHz", "up": "混乱沉睡",
        "duration": 1200.0, "view": 3580000, "pages": 1}
META_LONG = {"title": "【东方原曲合集】正作、旧作、官方专辑共793P", "up": "Josany",
             "duration": 172557.0, "view": 3660000, "pages": 793}
META_SMALL = {"title": "古明地恋AI桌宠 Koishi AI Pet v1.7.0", "up": "古明地洞",
              "duration": 480.0, "view": 185, "pages": 1}

P_EMPTY = {"words": [], "ups": [], "maxDurationMin": 0, "minPlay": 0}

print("=== ① 闸门规则 ===")
eq("全关 ⇒ 放行", m._gate_one(META, P_EMPTY), "")
eq("屏蔽词命中", m._gate_one(META, {**P_EMPTY, "words": ["泰拉瑞亚"]}) != "", True)
eq("屏蔽词没命中", m._gate_one(META, {**P_EMPTY, "words": ["考研"]}), "")
eq("屏蔽 UP 命中", m._gate_one(META, {**P_EMPTY, "ups": ["混乱沉睡"]}) != "", True)
eq("屏蔽 UP 大小写无关", m._gate_one(META, {**P_EMPTY, "ups": ["混乱"]}) != "", True)
eq("时长超限被拦", m._gate_one(META, {**P_EMPTY, "maxDurationMin": 10}) != "", True)
eq("时长没超 ⇒ 放行", m._gate_one(META, {**P_EMPTY, "maxDurationMin": 30}), "")
eq("793P 合集豁免时长", m._gate_one(META_LONG, {**P_EMPTY, "maxDurationMin": 10}), "")
eq("播放量低于下限被拦", m._gate_one(META_SMALL, {**P_EMPTY, "minPlay": 1000}) != "", True)
eq("播放量够 ⇒ 放行", m._gate_one(META_SMALL, {**P_EMPTY, "minPlay": 100}), "")
eq("**185 播放那条默认必须放行**", m._gate_one(META_SMALL, P_EMPTY), "")

print("\n=== ② _prefs 读到的规则 ===")
p = m._prefs()
print("   words:", p["words"])
print("   banUps:", p["ups"], " maxDurationMin:", p["maxDurationMin"], " minPlay:", p["minPlay"])
print("   （现场值可能是你用 /gate 设过的，这里只校验类型）")
eq("时长/播放量都是整数", (isinstance(p["maxDurationMin"], int), isinstance(p["minPlay"], int)), (True, True))
eq("词来自 config.json 的 excludeWords", len(p["words"]) > 0, True)


async def real():
    print("\n=== ③ 对真实 BV 跑一遍（只读）===")
    meta = await m._fetch_meta("BV19Kjf6cEh8")
    print("   ", {k: meta[k] for k in ("title", "up", "view")}, "时长", round(meta["duration"] / 60), "分钟")
    eq("真实视频元信息齐全", all([meta["title"], meta["up"], meta["view"] > 0, meta["duration"] > 0]), True)

    text = ("今天挑了 1 条：\n[1] 泰拉瑞亚 32位RISC-V CPU\n"
            "https://b23.tv/BV19Kjf6cEh8 · 原版电路搭CPU\n")
    # 先强制一份「规则全关」的 prefs 再测（不依赖现场配置）
    pf0 = DUTY / "prefs.json"
    backup0 = pf0.read_text(encoding="utf-8")
    pf0.write_text(json.dumps({"banUps": [], "maxDurationMin": 0, "minPlay": 0}, ensure_ascii=False),
                   encoding="utf-8")
    try:
        bad = await m._delivery_check(text)
        eq("规则全关时这条能过闸", bad, [])
    finally:
        pf0.write_text(backup0, encoding="utf-8")

    # 临时把上限压到 1 分钟，验证闸门真的会拦（用完还原）
    pf = DUTY / "prefs.json"
    backup = pf.read_text(encoding="utf-8")
    try:
        pf.write_text(json.dumps({**json.loads(backup), "maxDurationMin": 1}, ensure_ascii=False), encoding="utf-8")
        bad2 = await m._delivery_check(text)
        eq("改了上限后立刻被拦", len(bad2), 1)
        eq("拒绝理由说清了为什么", "超过你设的 1 分钟上限" in bad2[0], True)
        print("     理由：", bad2[0])
    finally:
        pf.write_text(backup, encoding="utf-8")
    # 还原后：行为应回到「配置写了什么就是什么」（现场可能本来就设了上限，别假设是 0）
    eq("还原后 prefs 回到原值", m._prefs()["maxDurationMin"], json.loads(backup)["maxDurationMin"])
    bad3 = await m._delivery_check(text)
    eq("还原后行为与配置一致", bool(bad3), m._prefs()["maxDurationMin"] > 0)


asyncio.run(real())
print(f"\n通过 {ok} · 失败 {fail}")
if fail:
    sys.exit(1)
