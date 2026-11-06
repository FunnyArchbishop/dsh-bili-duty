"""验证托盘的「顺带启动宿主」：宿主在跑时应该直接返回"已经在跑"。

⚠️ 真正的 spawn 分支测不了 —— 测它就得杀掉正在服务本次对话的 DSH 宿主。
   所以这里只验证：①路径能解析 ②已启动时会短路 ③命令拼得出来。
"""
import importlib.util
import pathlib
import sys

SRC = pathlib.Path(r"D:\What Can IC\deepseekBilibili\bili-profile\托盘控制台.py")
spec = importlib.util.spec_from_file_location("tray", SRC)
m = importlib.util.module_from_spec(spec)
sys.modules["tray"] = m
spec.loader.exec_module(m)

print("=== ① 路径解析 ===")
node = getattr(m.core, "NODE", "")
dsh = getattr(m.core, "DSH_BIN", "")
print("   node   :", node, "存在:", pathlib.Path(node).exists() if node else False)
print("   dsh bin:", dsh, "存在:", pathlib.Path(dsh).exists() if dsh else False)
assert pathlib.Path(node).exists() and pathlib.Path(dsh).exists(), "路径解析失败"

print("\n=== ② 宿主在跑时应该短路 ===")
print("   host_up() =", m.host_up())
msg = m.start_host()
print("   start_host() ->", msg)
assert msg == "宿主已经在跑", f"短路失效：{msg}"

print("\n=== ③ 拼出来的启动命令 ===")
print("   将执行:", [node, dsh, "web"])

print("\n=== ④ 托盘菜单项 ===")
src = SRC.read_text(encoding="utf-8")
for item in ("启动宿主（dsh web）", "关闭宿主", "打开 DSH 网页"):
    print(f"   {'✓' if item in src else '✗'} {item}")

print("\n=== ⑤ 无黑框 / 单实例 / 打开命令行 ===")
for fn in ("hide_own_console", "relaunch_without_console", "_ideal_interpreter",
           "open_terminal", "another_instance", "mark_instance", "unmark_instance"):
    ok = callable(getattr(m, fn, None))
    print(f"   {'✓' if ok else '✗'} {fn}()")
    assert ok, f"缺函数 {fn}"

pyw = m._ideal_interpreter()
print("   理想解释器:", pyw)
assert pyw is not None and pathlib.Path(pyw).exists(), "找不到 venv 的 pythonw"
assert "pythonw.exe" in str(pyw).lower()
m.hide_own_console()          # 没有控制台时应该安静地什么也不做

for item in ("命令行", '"term"', "open_terminal()", "打开命令行"):
    ok = item in src
    print(f"   {'✓' if ok else '✗'} 源码里有 {item}")
    assert ok, f"缺 {item}"
assert "CREATE_NEW_CONSOLE" in src or "0x00000010" in src

# 单实例：用临时 pid 文件，别动正在跑的那个实例
import os
import tempfile

_old_pid = m.PID_FILE
m.PID_FILE = pathlib.Path(tempfile.gettempdir()) / "bili-tray-test.pid"
try:
    m.unmark_instance()
    assert m.another_instance() is False, "没 pid 文件时不该算有实例"
    m.mark_instance()
    assert m.another_instance() is False, "自己不该算另一个实例"
    m.PID_FILE.write_text("999999999", encoding="utf-8")
    assert m.another_instance() is False, "死进程不该挡住启动"
    ppid = os.getppid()
    m.PID_FILE.write_text(str(ppid), encoding="utf-8")
    print(f"   父进程 {ppid} 还活着 ⇒ another_instance() =", m.another_instance())
    assert m.another_instance() is True, "活着的 pid 应该挡住重复启动"
    m.PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    m.unmark_instance()
    print("   unmark 之后文件还在吗:", m.PID_FILE.exists())
    assert not m.PID_FILE.exists(), "unmark_instance 没删掉自己的 pid 文件"
finally:
    m.PID_FILE = _old_pid
print("   ✓ 判活用 OpenProcess；绝不用 os.kill(pid, 0) —— Windows 上那是 TerminateProcess")
import re

_judge = src.split("def _pid_alive")[1].split("\ndef ")[0]
_code = re.sub(r'""".*?"""', "", _judge, flags=re.S)   # 注释里提到 os.kill 不算
assert "OpenProcess" in _code and "os.kill" not in _code

print("\n=== ⑥ 无黑框启动器 启动控制台.vbs ===")
vbs = SRC.parent / "启动控制台.vbs"
if not vbs.exists():
    print("   — 还没生成（patches/应用补丁.py 会生成）")
else:
    raw = vbs.read_bytes()
    assert raw[:2] == b"\xff\xfe", "必须是 UTF-16 LE BOM，否则 wscript 读坏中文路径"
    text = raw.decode("utf-16-le")
    assert "pythonw.exe" in text and "托盘控制台.py" in text
    assert ", 0," in text.replace("  ", " "), "window style 必须是 0（隐藏）"
    print("   ✓ UTF-16 LE / 路径正确 / window style 0")
    print("   ", [ln for ln in text.splitlines() if ln.startswith("sh.Run")][0][:110])

print("\n✓ 宿主启动逻辑就绪（spawn 分支等下次开机实测）")
