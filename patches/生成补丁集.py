#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成补丁集：拿上游原始包 + 我们改过的版本做真 diff（支持多个文件）。

用法：
    python patches/生成补丁集.py <解压出来的上游包目录> [已安装的插件目录]

    mkdir /tmp/base && tar -xzf dsh-bili-scroll-2.3.1.tgz -C /tmp/base
    python patches/生成补丁集.py /tmp/base

产物（都写在本文件旁边）：
    <name>/base-<版本>.<ext>   上游原样
    <name>/patched.<ext>       我们维护的版本  ←「也能改」就是改这个
    <name>/<name>.patch        两者的 unified diff
    <name>/SHA256.txt          指纹，应用补丁.py 靠它判断状态
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent

# (补丁目录名, 插件根目录下的相对路径) —— 要加新文件就在这里加一行
FILES = [
    ("mcp_server", "vendor/bilibili-mcp/mcp_server.py"),
    ("index_js", "index.js"),
]


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def gen_one(name: str, rel: str, base_root: pathlib.Path, installed: pathlib.Path) -> bool:
    out = HERE / name
    out.mkdir(parents=True, exist_ok=True)
    base_src = base_root / "package" / rel
    if not base_src.exists():
        base_src = base_root / rel
    cur_src = installed / rel
    for p in (base_src, cur_src):
        if not p.exists():
            print(f"  找不到：{p}", file=sys.stderr)
            return False

    version = "unknown"
    try:
        pkg = base_root / "package" / "package.json"
        version = json.loads(pkg.read_text(encoding="utf-8")).get("version") or version
    except Exception:
        pass

    ext = pathlib.Path(rel).suffix or ".txt"
    base = out / f"base-{version}{ext}"
    patched = out / f"patched{ext}"
    shutil.copy2(base_src, base)
    shutil.copy2(cur_src, patched)

    r = subprocess.run(["git", "diff", "--no-index", "--", base.name, patched.name],
                       cwd=str(out), capture_output=True)
    diff = r.stdout.decode("utf-8", "replace")
    if not diff.strip():
        print(f"  {name}: 与基线**完全一致**（没改动？），不生成 patch")
        return True
    diff = re.sub(r"^--- a/.*$", "--- a/" + rel, diff, flags=re.M)
    diff = re.sub(r"^\+\+\+ b/.*$", "+++ b/" + rel, diff, flags=re.M)
    diff = re.sub(r"^diff --git .*$", "diff --git a/" + rel + " b/" + rel, diff, flags=re.M)

    # ⚠️ 必须 newline="\n"：Windows 上 Python 默认把 \n 翻成 \r\n，
    #    而补丁描述的文件是 LF ⇒ 行尾对不上，git apply 全部失败（踩过）
    (out / f"{name}.patch").write_text(diff, encoding="utf-8", newline="\n")
    (out / "SHA256.txt").write_text(
        f"# {rel} 的上游基线 / 我们打完后 的指纹\n"
        f"base    {sha(base)}\npatched {sha(patched)}\n", encoding="utf-8", newline="\n")

    added = sum(1 for l in diff.splitlines() if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff.splitlines() if l.startswith("-") and not l.startswith("---"))
    print(f"  {name:12} 基线 {version:8} {base.stat().st_size:>7} → {patched.stat().st_size:>7} 字节"
          f"　补丁 +{added}/-{removed}")
    return True


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    base_root = pathlib.Path(sys.argv[1])
    installed = pathlib.Path(
        sys.argv[2] if len(sys.argv) > 2
        else (pathlib.Path(os.environ.get("DSH_HOME") or (pathlib.Path.home() / ".dsh"))
              / "profiles" / "web" / "node_modules" / "dsh-bili-scroll"))
    print(f"基线包：{base_root}\n已安装：{installed}\n")
    ok = all(gen_one(name, rel, base_root, installed) for name, rel in FILES)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
