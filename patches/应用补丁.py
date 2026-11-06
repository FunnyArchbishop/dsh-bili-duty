#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""应用 / 检查 / 回退本仓库对 dsh-bili-scroll 的补丁（支持多个文件）。

为什么不是 `git apply`：
    补丁要打到 `~/.dsh/profiles/<profile>/node_modules/dsh-bili-scroll/` 里，
    那是个 npm 装出来的目录，**不是 git 仓库**（git apply 会报 "must be run in a work tree"）。
    所以这里按 **sha256 比对状态 + 整文件铺**，行为等价而且更可控：
        · 目标 == 上游基线   ⇒ 可应用
        · 目标 == 我们改完的 ⇒ 已应用（幂等跳过）
        · 其它               ⇒ 上游变了 / 被别人改过 ⇒ **拒绝动手**，让你对照 .patch 手工合并

    ⚠️ 改完要**重启 DSH** 才生效（插件是宿主进程加载的，不像 mcp_server.py 每轮重读）。

用法：
    python patches/应用补丁.py --check     只看状态
    python patches/应用补丁.py             应用（幂等，可重复跑）
    python patches/应用补丁.py --revert    用 .orig-* 备份还原
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
CORDIS = HERE / "cordis.patch.yml"

# 下面要打 ✅/⚠️ 这些符号，GBK 控制台下 print 会直接 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# (补丁目录名, 插件根目录下的相对路径, 是否还有一份在插件家目录)
FILES = [
    ("mcp_server", "vendor/bilibili-mcp/mcp_server.py", True),
    ("index_js", "index.js", False),
]


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dsh_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DSH_HOME") or (pathlib.Path.home() / ".dsh"))


def plugin_root(profile: str) -> pathlib.Path | None:
    env = os.environ.get("BILI_PLUGIN_DIR")
    if env:
        return pathlib.Path(env)
    base = dsh_home() / "profiles"
    for d in sorted(base.glob("*/node_modules/dsh-bili-scroll")):
        # d = <home>/profiles/<profile>/node_modules/dsh-bili-scroll
        if profile and d.parent.parent.name != profile:
            continue
        return d
    return None


def duty_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("BILI_DUTY_HOME") or (dsh_home() / "bili-duty"))


def state_of(p: pathlib.Path, s_base: str, s_patched: str) -> str:
    if not p.exists():
        return "missing"
    s = sha(p)
    if s == s_patched:
        return "applied"
    if s == s_base:
        return "ready"
    return "conflict"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只报告状态，不动文件")
    ap.add_argument("--revert", action="store_true", help="用 .orig-* 备份还原")
    ap.add_argument("--profile", default="web", help="补哪个 profile 的插件（默认 web）")
    args = ap.parse_args()

    root = plugin_root(args.profile)
    rc = 0
    saw_index = False

    for name, rel, also_home in FILES:
        d = HERE / name
        patched = next(iter(sorted(d.glob("patched.*"))), None)
        if patched is None:
            print(f"缺 {d}/patched.*（先跑 生成补丁集.py）", file=sys.stderr)
            return 2
        base = next((p for p in sorted(d.glob("base-*")) if p != patched), None)
        if base is None:
            print(f"缺 {d}/base-*（先跑 生成补丁集.py）", file=sys.stderr)
            return 2
        s_base, s_patched = sha(base), sha(patched)

        targets: list[pathlib.Path] = []
        if root is not None:
            targets.append(root / rel)
        if also_home:
            targets.append(duty_home() / rellib_name(rel))
        if name == "index_js":
            saw_index = True

        print(f"\n=== {name}（{rel}）基线 {s_base[:12]}… → 改后 {s_patched[:12]}…")
        if not targets:
            print("  — 找不到插件目录（用 BILI_PLUGIN_DIR 或 --profile 指过去）")

        for p in targets:
            st = state_of(p, s_base, s_patched)
            tag = {"applied": "✅ 已应用", "ready": "🔧 可应用",
                   "conflict": "⚠️ 上游变了/被改过", "missing": "— 不存在"}[st]
            print(f"  {tag:22} {p}")

            if args.check or st == "missing":
                if st == "conflict":
                    rc = 1
                continue

            if args.revert:
                baks = sorted(p.parent.glob(p.name + ".orig-*"))
                if baks:
                    shutil.copy2(baks[-1], p)
                    print(f"    已还原自备份 {baks[-1].name}")
                else:
                    shutil.copy2(base, p)
                    print("    没有备份 ⇒ 直接铺回上游基线")
                continue

            if st == "applied":
                continue
            if st == "conflict":
                print(f"    ⛔ 不动它。请对照 patches/{name}/{name}.patch 手工合并，"
                      f"或把上游新版本另存为 base-<版本>{base.suffix} 后重跑 生成补丁集.py")
                rc = 1
                continue

            stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            bak = p.with_name(p.name + ".orig-" + stamp)
            shutil.copy2(p, bak)
            shutil.copy2(patched, p)
            print(f"    已打补丁（原文件备份为 {bak.name}）")

    # profile 补丁：只在缺失时放进去（不覆盖你手改过的）
    prof = dsh_home() / "profiles" / "bili-duty" / "cordis.patch.yml"
    if CORDIS.exists():
        if not prof.exists():
            if not args.check and not args.revert:
                dh = duty_home()
                prof.parent.mkdir(parents=True, exist_ok=True)
                text = CORDIS.read_text(encoding="utf-8").replace("@DUTY_HOME@", dh.as_posix())
                prof.write_text(text, encoding="utf-8", newline="\n")
                print(f"\n已写入 profile 补丁：{prof}")
            else:
                print(f"\nprofile 补丁缺失（可写入）：{prof}")
        else:
            print(f"\nprofile 补丁已存在，没动：{prof}")

    if saw_index:
        print("\n⚠️ index.js 的改动要**重启 DSH** 才生效（插件是宿主进程加载的）")

    write_launcher(args.check or args.revert)

    print("\n完成" + ("（有问题，见上面 ⚠️）" if rc else "，一切正常"))
    return rc


def rellib_name(rel: str) -> str:
    """插件包里的相对路径 → 家目录里对应的文件名（只有 mcp_server.py 这一份）"""
    return pathlib.Path(rel).name


def write_launcher(check: bool) -> None:
    """生成「无黑框启动器」bili-profile/启动控制台.vbs。

    为什么要有：这个 uv venv 里 python.exe 和 pythonw.exe 是同一份 console 子系统复制
    （各 45568 字节），直接启动必带黑框 —— 换 pythonw 也没用，试过。
    只有 wscript 的 Run(cmd, 0, ...)（window style 0）才真不给窗口。
    文件必须写成 UTF-16 LE + BOM：wscript 按 ANSI 读 UTF-8 会把中文路径弄坏。
    """
    tpl = HERE / "launcher" / "启动控制台.vbs.tpl"
    if not tpl.exists():
        return
    prof_dir = pathlib.Path(os.environ.get("BILI_PROFILE_DIR") or (HERE.parent / "bili-profile"))
    target = prof_dir / "启动控制台.vbs"
    pyw = duty_home() / ".venv" / "Scripts" / "pythonw.exe"
    script = prof_dir / "托盘控制台.py"
    print(f"\n=== 启动器（{target.name}）")
    if not prof_dir.exists():
        print(f"  — 目录不存在，跳过：{prof_dir}（用 BILI_PROFILE_DIR 指过去）")
        return
    if not pyw.exists():
        print(f"  ⚠️ 没找到 {pyw} —— 先在插件设置里跑一次 bili_setup 建 venv")
    if not script.exists():
        print(f"  ⚠️ 没找到 {script}")
    if check:
        print(f"  {'已存在' if target.exists() else '可生成'}：{target}")
        return
    text = (tpl.read_text(encoding="utf-8")
            .replace("@PYTHONW@", str(pyw))
            .replace("@SCRIPT@", str(script)))
    target.write_bytes(b"\xff\xfe" + text.replace("\n", "\r\n").encode("utf-16-le"))
    print(f"  已写入 {target}（UTF-16 LE）")
    print('  桌面快捷方式请指向： wscript.exe "…\\启动控制台.vbs"')


if __name__ == "__main__":
    sys.exit(main())
