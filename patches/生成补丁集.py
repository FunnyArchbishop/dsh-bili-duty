#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成补丁集：拿上游原始包 + 我们改过的版本做真 diff。

用法：
    python patches/生成补丁集.py <解压出来的上游包目录> [已安装的插件目录]

    # 例：先把 npm 包解开
    mkdir /tmp/base && tar -xzf dsh-bili-scroll-2.3.1.tgz -C /tmp/base
    python patches/生成补丁集.py /tmp/base

产物（都写到本文件旁边）：
    mcp_server/base-<版本>.py    上游原样
    mcp_server/patched.py        我们维护的版本  ← 「也能改」就是改这个
    mcp_server/mcp_server.patch  两者的 unified diff（审阅 / 上游升级时手工合并）
    mcp_server/SHA256.txt        指纹，应用补丁.py 靠它判断状态
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "mcp_server"
REL = "vendor/bilibili-mcp/mcp_server.py"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    base_root = pathlib.Path(sys.argv[1])
    installed = pathlib.Path(
        sys.argv[2] if len(sys.argv) > 2
        else (pathlib.Path(os.environ.get("DSH_HOME") or (pathlib.Path.home() / ".dsh"))
              / "profiles" / "web" / "node_modules" / "dsh-bili-scroll"))

    base_src = base_root / "package" / REL
    if not base_src.exists():
        base_src = base_root / REL
    cur_src = installed / REL
    for p in (base_src, cur_src):
        if not p.exists():
            print(f"找不到：{p}", file=sys.stderr)
            return 2

    # 版本号只用来命名基线文件，读不到就叫 base.py
    version = "unknown"
    try:
        pkg = (base_root / "package" / "package.json")
        version = __import__("json").loads(pkg.read_text(encoding="utf-8")).get("version") or version
    except Exception:
        pass

    OUT.mkdir(parents=True, exist_ok=True)
    base = OUT / f"base-{version}.py"
    patched = OUT / "patched.py"
    shutil.copy2(base_src, base)
    shutil.copy2(cur_src, patched)

    r = subprocess.run(["git", "diff", "--no-index", "--", base.name, "patched.py"],
                       cwd=str(OUT), capture_output=True)
    diff = r.stdout.decode("utf-8", "replace")
    diff = re.sub(r"^--- a/.*$", "--- a/" + REL, diff, flags=re.M)
    diff = re.sub(r"^\+\+\+ b/.*$", "+++ b/" + REL, diff, flags=re.M)
    diff = re.sub(r"^diff --git .*$", "diff --git a/" + REL + " b/" + REL, diff, flags=re.M)

    # ⚠️ 必须 newline="\n"：Windows 上 Python 默认把 \n 翻成 \r\n，
    #    而补丁描述的文件是 LF ⇒ 行尾对不上，git apply 全部失败（踩过）
    (OUT / "mcp_server.patch").write_text(diff, encoding="utf-8", newline="\n")
    (OUT / "SHA256.txt").write_text(
        "# 上游基线 / 我们打完后 的指纹。应用补丁.py 拿它判断「可应用 / 已应用 / 上游变了」\n"
        f"base    {sha(base)}\npatched {sha(patched)}\n", encoding="utf-8", newline="\n")

    added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    print(f"基线 {version:10} {base.stat().st_size:>7} 字节  {sha(base)[:16]}")
    print(f"改后            {patched.stat().st_size:>7} 字节  {sha(patched)[:16]}")
    print(f"补丁 +{added} / -{removed} 行 -> {(OUT / 'mcp_server.patch').name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
