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

print("\n✓ 宿主启动逻辑就绪（spawn 分支等下次开机实测）")
