#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""应用 / 检查 / 回退本仓库对 dsh-bili-scroll 的补丁。

为什么不是 `git apply`：
    补丁要打到 `~/.dsh/profiles/<profile>/node_modules/dsh-bili-scroll/` 里，
    那是个 npm 装出来的目录，**不是 git 仓库**（git apply 会报 "must be run in a work tree"）。
    所以这里按 **sha256 比对状态 + 整文件铺**，行为等价而且更可控：
        · 目标 == 上游基线   ⇒ 可应用
        · 目标 == 我们改完的 ⇒ 已应用（幂等跳过）
        · 其它               ⇒ 上游变了 / 被别人改过 ⇒ **拒绝动手**，让你对照 .patch 手工合并

用法：
    python patches/应用补丁.py --check     只看状态
    python patches/应用补丁.py             应用（幂等，可重复跑）
    python patches/应用补丁.py --revert    用 .orig-* 备份还原
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
PKG = HERE / "mcp_server"
BASE = PKG / "base-2.3.1.py"
PATCHED = PKG / "patched.py"
CORDIS = HERE / "cordis.patch.yml"

REL = pathlib.Path("vendor") / "bilibili-mcp" / "mcp_server.py"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dsh_home() -> pathlib.Path:
    return pathlib.Path(os.environ.get("DSH_HOME") or (pathlib.Path.home() / ".dsh"))


def plugin_targets(profile: str) -> list[pathlib.Path]:
    """插件里那份 + 家目录那份（ensureHomeFiles 会在两者不一致时用插件那份覆盖家里的）"""
    out = []
    env = os.environ.get("BILI_PLUGIN_DIR")
    if env:
        out.append(pathlib.Path(env) / REL)
    else:
        base = dsh_home() / "profiles"
        for d in sorted(base.glob("*/node_modules/dsh-bili-scroll")):
            # d = <home>/profiles/<profile>/node_modules/dsh-bili-scroll
            # ⇒ 上一层是 node_modules，再上一层才是 profile 名
            if profile and d.parent.parent.name != profile:
                continue
            out.append(d / REL)
    duty_home = pathlib.Path(os.environ.get("BILI_DUTY_HOME") or (dsh_home() / "bili-duty"))
    out.append(duty_home / "mcp_server.py")
    return out


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

    for f in (BASE, PATCHED):
        if not f.exists():
            print(f"缺文件：{f}（先跑 生成补丁集.py）", file=sys.stderr)
            return 2
    s_base, s_patched = sha(BASE), sha(PATCHED)
    print(f"补丁集：基线 {s_base[:12]}…  改后 {s_patched[:12]}…  "
          f"（+{PATCHED.stat().st_size - BASE.stat().st_size} 字节）\n")

    targets = plugin_targets(args.profile)
    rc = 0
    for p in targets:
        st = state_of(p, s_base, s_patched)
        tag = {"applied": "✅ 已应用", "ready": "🔧 可应用",
               "conflict": "⚠️ 上游变了/被改过", "missing": "— 不存在"}[st]
        print(f"{tag:22} {p}")

        if args.check or st == "missing":
            if st == "conflict":
                rc = 1
            continue

        if args.revert:
            # 有 .orig 备份就用最新的；没有就直接铺回基线 —— 两者都等于"回到上游原样"
            baks = sorted(p.parent.glob(p.name + ".orig-*"))
            if baks:
                shutil.copy2(baks[-1], p)
                print(f"    已还原自备份 {baks[-1].name}")
            else:
                shutil.copy2(BASE, p)
                print("    没有备份 ⇒ 直接铺回上游基线")
            continue

        if st == "applied":
            continue
        if st == "conflict":
            print("    ⛔ 不动它。请对照 patches/mcp_server/mcp_server.patch 手工合并，"
                  "或把上游新版本另存为 base-<版本>.py 后重跑 生成补丁集.py")
            rc = 1
            continue

        stamp = __import__("datetime").datetime.now().strftime("%Y%m%d-%H%M%S")
        bak = p.with_name(p.name + ".orig-" + stamp)
        shutil.copy2(p, bak)
        shutil.copy2(PATCHED, p)
        print(f"    已打补丁（原文件备份为 {bak.name}）")

    # profile 补丁：只在缺失时放进去（不覆盖你手改过的）。
    # 仓库里那份写的是占位符 @DUTY_HOME@，铺的时候替换成本机真实路径。
    prof = dsh_home() / "profiles" / "bili-duty" / "cordis.patch.yml"
    if CORDIS.exists():
        if not prof.exists():
            if not args.check and not args.revert:
                duty_home = pathlib.Path(os.environ.get("BILI_DUTY_HOME") or (dsh_home() / "bili-duty"))
                prof.parent.mkdir(parents=True, exist_ok=True)
                text = CORDIS.read_text(encoding="utf-8").replace("@DUTY_HOME@", duty_home.as_posix())
                prof.write_text(text, encoding="utf-8", newline="\n")
                print(f"\n已写入 profile 补丁：{prof}")
            else:
                print(f"\nprofile 补丁缺失（可写入）：{prof}")
        else:
            print(f"\nprofile 补丁已存在，没动：{prof}")

    print("\n完成" + ("（有问题，见上面 ⚠️）" if rc else "，一切正常"))
    return rc


if __name__ == "__main__":
    sys.exit(main())
