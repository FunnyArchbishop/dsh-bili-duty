"""写一个无窗口启动器（wscript + VBS 的 Run 窗口样式 0），并重挂计划任务。

为什么不用 pythonw.exe：
  ⚠️ 2026-11-05 实测：这个 venv（uv 管的）里 pythonw.exe 的 PE subsystem = 3，
     也就是说它**就是个控制台程序**，并不是 CPython 那个 GUI 子系统的 pythonw ⇒
     用它当计划任务的动作照样弹黑框 ✗
  ⇒ 改成 wscript.exe 跑一个 VBS，`WshShell.Run(cmd, 0, True)` 的 0 = 窗口隐藏，
    这才对任何控制台程序都有效；子进程（node）已在自己的代码里加了 CREATE_NO_WINDOW。
"""
import json
import os
import pathlib
import struct

HERE = pathlib.Path(__file__).resolve().parent
try:
    LOCAL = json.loads((HERE / "local.json").read_text(encoding="utf-8"))
except Exception:
    LOCAL = {}

VBS = HERE / "console-launch.vbs"
PY = LOCAL.get("pythonExe") or "python"
SCRIPT = str(HERE / "私信控制台.py")

# 先确认一下 pythonw 到底是不是真无窗口（留证据）
for name in ("python.exe", "pythonw.exe"):
    p = pathlib.Path(PY).parent / name
    b = p.read_bytes()
    pe = struct.unpack_from("<I", b, 0x3C)[0]
    sub = struct.unpack_from("<H", b, pe + 0x5C)[0]
    print(f"{name}: subsystem={sub} ({'GUI/无窗口' if sub == 2 else 'CONSOLE/有窗口'})")

body = (
    "' 刷B站控制台 · 无窗口启动器（由计划任务 DSH-BiliScoring 每分钟调用一次）\n"
    "' 0 = 窗口隐藏；True = 等它跑完（这样计划任务历史里能看到耗时）\n"
    "' 额外参数原样透传：wscript console-launch.vbs --simulate-chat \"...\"\n"
    "Option Explicit\n"
    "Dim sh, cmd, i, extra\n"
    'Set sh = CreateObject("WScript.Shell")\n'
    f'cmd = """" & "{PY}" & """ """ & "{SCRIPT}" & """"\n'
    'extra = ""\n'
    "For i = 0 To WScript.Arguments.Count - 1\n"
    '  extra = extra & " """ & WScript.Arguments(i) & """"\n'
    "Next\n"
    "cmd = cmd & extra\n"
    "sh.Run cmd, 0, True\n"
)
# wscript 读 .vbs 默认按 ANSI；写 UTF-16 LE + BOM 才不会被中文路径搞乱
VBS.write_text(body, encoding="utf-16-le")
raw = VBS.read_bytes()
if not raw.startswith(b"\xff\xfe"):
    VBS.write_bytes(b"\xff\xfe" + raw)
print("已写：", VBS, VBS.stat().st_size, "字节（UTF-16 LE + BOM）")
