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

print("\n=== ⑦ 图标（抠掉白底的插画）===")
png, ico = SRC.parent / "图标.png", SRC.parent / "图标.ico"
assert callable(getattr(m, "load_icon", None)), "缺 load_icon()"
assert callable(getattr(m, "apply_window_icon", None)), "缺 apply_window_icon()"
if png.exists():
    from PIL import Image

    im = Image.open(png)
    print(f"   {png.name}: {im.size} {im.mode} {png.stat().st_size / 1024:.0f} KB")
    assert im.mode == "RGBA", "图标必须是 RGBA（要有透明底）"
    assert im.size == (512, 512)

    # ① 四角必须透明 —— 这就是"去掉白边背景"
    al = im.getchannel("A")
    w, h = im.size
    corners = [al.getpixel((0, 0)), al.getpixel((w - 1, 0)), al.getpixel((0, h - 1)), al.getpixel((w - 1, h - 1))]
    print("   四角 alpha:", corners)
    assert max(corners) == 0, "四角不透明 ⇒ 白边没去掉"

    # ② 中心必须不透明（图案还在）
    print("   中心 alpha:", al.getpixel((w // 2, h // 2)))
    assert al.getpixel((w // 2, h // 2)) == 255

    # ③ 边缘要有半透明过渡（抗锯齿），不能是硬切
    semi = sum(1 for a in al.get_flattened_data() if 0 < a < 255)
    print(f"   半透明过渡像素: {semi}")
    assert semi > 100, "边缘没有抗锯齿"

    # ④ 托盘/窗口图标走的就是这张图，而不是画出来的备用图
    ic = m.load_icon(64)
    print("   load_icon(64) ->", ic.size, ic.mode)
    assert ic.size == (64, 64) and ic.mode == "RGBA"
    ref = im.resize((64, 64), Image.LANCZOS)
    same = list(ic.get_flattened_data()) == list(ref.get_flattened_data())
    print("   与 图标.png 缩放到 64 完全一致:", same)
    assert same, "托盘图标没走 图标.png"

if ico.exists():
    from PIL import Image

    ic2 = Image.open(ico)
    got = sorted(ic2.info.get("sizes", []))
    print(f"   {ico.name}: {ico.stat().st_size / 1024:.0f} KB，内含 {len(got)} 个尺寸 {got}")
    assert (16, 16) in got and (256, 256) in got, "ICO 缺小尺寸或 256 大图标"

print("\n=== ⑧ 按钮状态机（界面是否「完备」的核心）===")
#  用真实 tk.Button 跑 App.sync_buttons 这个**未绑定方法**：
#  不实例化 App ⇒ 不会起 poller / 不会真的去启宿主 / 不会发私信。
from types import SimpleNamespace

try:
    import tkinter as tk

    _root = tk.Tk()
    _root.withdraw()
except Exception as e:                                   # 没桌面就跳过这组
    print(f"   ⚠️ 跳过（建不了 Tk 窗口）：{e}")
    _root = None

if _root is not None:
    ACTS = ("scan", "dsh", "host", "restarthost", "term", "toggle", "report", "refresh")
    btns = {a: tk.Button(_root, text="-") for a in ACTS}
    fake = SimpleNamespace(btns=btns, busy={"host": False}, _host=False, scanning=False)

    def st(a):
        return btns[a].cget("state")

    def tx(a):
        return btns[a].cget("text")

    # ① 宿主没跑：启动宿主，且依赖宿主的三项全灰
    m.App.sync_buttons(fake)
    print(f"   宿主没跑 → [{tx('host')}]  dsh={st('dsh')}  restart={st('restarthost')}")
    assert tx("host") == "启动宿主" and st("host") == "normal"
    assert st("dsh") == "disabled" and st("restarthost") == "disabled"
    assert st("term") == "normal" and st("refresh") == "normal"      # 恒可用

    # ② 宿主在跑：按钮就该变成「关闭宿主」
    fake._host = True
    m.App.sync_buttons(fake)
    print(f"   宿主在跑 → [{tx('host')}]  dsh={st('dsh')}")
    assert tx("host") == "关闭宿主"
    assert st("dsh") == "normal" and st("restarthost") == "normal"

    # ③ 启动/关闭进行中：按钮禁用 + 文本变进行中
    fake.busy["host"] = True
    m.App.sync_buttons(fake)
    print(f"   进行中   → [{tx('host')}] state={st('host')}  dsh={st('dsh')}")
    assert st("host") == "disabled" and "中" in tx("host")
    assert st("dsh") == "disabled" and st("restarthost") == "disabled"

    # ④ 扫描中：不能重复点
    fake.busy["host"] = False
    fake._host = True
    fake.scanning = True
    m.App.sync_buttons(fake)
    print(f"   扫描中   → [{tx('scan')}] state={st('scan')}")
    assert tx("scan") == "扫描中…" and st("scan") == "disabled"
    fake.scanning = False

    # ⑤ 暂停轮询：按钮文本要反过来
    m.poller.paused = True
    m.App.sync_buttons(fake)
    print(f"   暂停中   → [{tx('toggle')}]")
    assert tx("toggle") == "继续轮询"
    m.poller.paused = False
    m.App.sync_buttons(fake)
    assert tx("toggle") == "暂停轮询"

    # ⑥ 报告按钮：今天没生成过就该是灰的
    today = m.core.now_bj().strftime("%Y-%m-%d")
    has = (m.core.OUT / f"{today}.md").exists()
    print(f"   报告按钮 → state={st('report')}（今天有报告={has}）")
    assert st("report") == ("normal" if has else "disabled")

    # ⑦ 输入框联动：空着禁用、有内容才亮
    v = tk.StringVar()
    b = tk.Button(_root, text="添加", state="disabled")
    m.App._bind_entry(fake, v, b)
    assert b.cget("state") == "disabled"
    v.set("东方project")
    assert b.cget("state") == "normal"
    v.set("   ")
    assert b.cget("state") == "disabled"
    print("   输入框   → 空=灰 / 有内容=亮 ✓")

    _root.destroy()
    print("   ✓ 状态机 7 项全过")

print("\n✓ 宿主启动逻辑就绪（spawn 分支等下次开机实测）")
