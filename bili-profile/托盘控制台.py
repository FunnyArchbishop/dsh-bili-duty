#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""托盘控制台 —— 「刷B站」的桌面控制台。

为什么要它（2026-11-05）：
    私信本质是**轮询**（B站 没有公开的推送协议），拿它当控制台注定慢半拍。
    所以把"我要看一眼 / 我要改一下"这两件事搬到桌面上：
      · 点托盘图标 → 出窗口，**即时**看到状态
      · 关窗口 → 缩到托盘继续跑（不退出）
      · 窗口里能改关键词 / 屏蔽词 / 闸门，能回答追问，能立刻扫一次 / 跑一轮
    私信那边就只剩它擅长的：**异步命令 + 通知**。

它会**接管轮询**：开着的时候每 15 秒扫一次私信（比计划任务的 60 秒快），
并写心跳文件；关掉之后计划任务照旧兜底。

用法：
    python 托盘控制台.py            正常启动（窗口 + 托盘）
    python 托盘控制台.py --no-tray  只开窗口（调试用，关窗口就退出）
    python 托盘控制台.py --selftest 不开界面，只打印它读到的状态（自测用）
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import pathlib
import queue
import subprocess
import sys
import threading
import time

HERE = pathlib.Path(__file__).resolve().parent
POLL_SECONDS = 15
API = "http://127.0.0.1:3080/api/bili-duty"


def _ideal_interpreter():
    """该用哪个解释器跑这个界面。

    首选是**插件配置里那个 venv 的 pythonw**（aiohttp / pystray / Pillow 都装在那儿，
    config.json 的 pythonPath 就是它）；退路才是跟当前解释器同目录的 pythonw.exe。
    只换成同目录的 pythonw 是不够的：系统 Python 里没有 aiohttp，
    轮询会一直报「No module named 'aiohttp'」。
    """
    cands = []
    try:
        p = (core.read_json(core.CFG, {}) or {}).get("pythonPath") or ""
        if p:
            cands.append(pathlib.Path(p).with_name("pythonw.exe"))
    except Exception:
        pass
    exe = pathlib.Path(sys.executable)
    if exe.name.lower().startswith("python"):
        cands.append(exe.with_name("pythonw.exe"))
    for c in cands:
        try:
            if c.exists():
                return c
        except Exception:
            pass
    return None


def hide_own_console() -> None:
    """如果自己带着一个黑框控制台，就地把它藏掉。

    为什么要这层：venv 的 pythonw.exe 是 console 子系统（跟 python.exe 同一份复制），
    走 vbs 启动才没有窗口；但万一使用者双击 .py 或从终端 python 起，黑框就出来了。
    ⚠️ 安全线：GetConsoleProcessList 里只有自己才藏 —— 要是还挂着 cmd/pwsh，
    那说明这是使用者的终端，藏了等于把他的窗口吞掉。
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        hwnd = k32.GetConsoleWindow()
        if not hwnd:
            return                                  # 本来就没有控制台，最理想
        arr = (ctypes.c_uint * 16)()
        n = k32.GetConsoleProcessList(arr, 16)
        if n != 1:
            return                                  # 还有别人挂着 ⇒ 不是我们的窗口
        ctypes.windll.user32.ShowWindow(hwnd, 0)    # SW_HIDE
    except Exception:
        pass


def relaunch_without_console() -> None:
    """跑在带控制台 / 不对的解释器下，就换成正确的 pythonw 重开自己，然后退出。

    为什么：双击 .py（或用终端 `python 托盘控制台.py`）会带一个黑框控制台窗口，
    而这是个常驻的托盘程序，那个窗口只会碍事（截图里那个写着「[追问] … 已发出」的就是）。
    ⚠️ 不用 ShowWindow 藏自己的控制台 —— 那会把使用者自己开着的终端一起藏掉。
    ⚠️ --selftest 要 stdout，不能重开。
    """
    if os.name != "nt" or "--selftest" in sys.argv:
        return
    pyw = _ideal_interpreter()
    if pyw is None:
        return
    try:
        if pathlib.Path(sys.executable).resolve() == pyw.resolve():
            return                            # 已经是它了，别再套娃
    except Exception:
        pass
    flags = 0x08000000                       # CREATE_NO_WINDOW，只给这个
    #  不用 DETACHED_PROCESS：对 console 子系统的程序它不保证没有窗口；
    #  CREATE_NO_WINDOW 才是「console 程序，但别开窗口」的准确说法。
    argv = list(sys.argv)
    try:                                     # 用绝对路径，别指望新进程的 cwd 一样
        argv[0] = str(pathlib.Path(argv[0]).resolve())
    except Exception:
        argv[0] = str(HERE / "托盘控制台.py")
    try:
        subprocess.Popen([str(pyw), *argv], cwd=str(HERE),
                         close_fds=True, creationflags=flags)
    except Exception:
        return                                # 换不起来就照常跑，别把程序搞死
    raise SystemExit(0)


def load_core():
    """复用 私信控制台.py 的全部逻辑（不重复造一遍读写/改配置的代码）"""
    spec = importlib.util.spec_from_file_location("bili_core", HERE / "私信控制台.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["bili_core"] = m
    spec.loader.exec_module(m)
    return m


core = load_core()


# ── 宿主在不在跑 ─────────────────────────────────────────────────────────
#    插件的 /api/bili-duty/* 要鉴权（401），试过 Bearer / cookie / 自定义头都不对，
#    不猜了。能不能跑值班轮只取决于 DSH 宿主在不在 —— 端口能连上就算在。
def host_up() -> bool:
    import socket
    try:
        with socket.create_connection(("127.0.0.1", 3080), timeout=0.35):
            return True
    except Exception:
        return False


# ── 单实例 ───────────────────────────────────────────────────────────────
PID_FILE = core.DUTY / "tray.pid"


def _pid_alive(pid: int) -> bool:
    """Windows 判活用 OpenProcess + GetExitCodeProcess。
    ⚠️ 不用 os.kill(pid, 0)：Windows 上它等价于 TerminateProcess，会把进程杀掉。"""
    if os.name != "nt" or pid <= 0:
        return False
    try:
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(h, ctypes.byref(code)):
                return False
            return code.value == 259                 # STILL_ACTIVE
        finally:
            k32.CloseHandle(h)
    except Exception:
        return False


def another_instance() -> bool:
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        return False
    return pid != os.getpid() and _pid_alive(pid)


def mark_instance() -> None:
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass


def unmark_instance() -> None:
    try:
        if PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except Exception:
        pass


def open_terminal() -> None:
    """在项目目录里开一个新的 cmd 窗口（零拼装：cwd 直接给，cmd /k 保持不关）"""
    try:
        subprocess.Popen(["cmd", "/k"], cwd=str(HERE),
                         creationflags=0x00000010)   # CREATE_NEW_CONSOLE
        core.append_log("托盘：打开命令行窗口")
    except Exception as e:
        core.append_log(f"托盘：开命令行失败 {e}")


def open_dsh() -> None:
    try:
        os.startfile("http://127.0.0.1:3080")     # noqa: S606 本机打开浏览器
    except Exception:
        pass

# ── 顺带把 DSH 宿主拉起来（2026-11-05 按使用者要求）───────────────────────
#    宿主 = `dsh web`：插件、定时器、/api/bili-duty/* 都在里面。
#    宿主没起 ⇒ 值班轮不会自动触发，控制台只能干扫私信。
_HOST = {"we_started": False}


def start_host(wait: float = 45.0) -> str:
    """没起就起一个（detached，不跟着控制台一起退出）。返回一句话状态。"""
    if host_up():
        return "宿主已经在跑"
    node, dsh = getattr(core, "NODE", "") or "", getattr(core, "DSH_BIN", "") or ""
    if not (node and dsh and pathlib.Path(node).exists() and pathlib.Path(dsh).exists()):
        return f"找不到 node 或 dsh（node={node} dsh={dsh}），先在 local.json 里填好"
    try:
        flags = 0
        if os.name == "nt":
            flags = 0x00000008 | 0x08000000        # DETACHED_PROCESS | CREATE_NO_WINDOW
        subprocess.Popen(
            [node, dsh, "web"],
            cwd=str(pathlib.Path.home()),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        _HOST["we_started"] = True
        core.append_log("托盘控制台：启动了 DSH 宿主（dsh web）")
    except Exception as e:
        return f"启动宿主失败：{e}"
    t0 = time.time()
    while time.time() - t0 < wait:
        if host_up():
            return f"宿主已启动（等了 {int(time.time() - t0)} 秒）"
        time.sleep(0.8)
    return f"宿主可能没起来（等了 {int(wait)} 秒还是连不上 3080）"


def stop_host() -> str:
    """只关我们起的那个 —— 别把使用者正在用的会话一起掐了"""
    if not host_up():
        return "宿主本来就没在跑"
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True,
                            encoding="utf-8", errors="replace",
                            creationflags=0x08000000 if os.name == "nt" else 0).stdout
        pids = {ln.split()[-1] for ln in out.splitlines()
                if ":3080" in ln and "LISTENING" in ln.upper() or (":3080" in ln and "LISTEN" in ln.upper())}
        pids = {x for x in pids if x.isdigit()}
        for pid in pids:
            subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        core.append_log(f"托盘控制台：关闭 DSH 宿主 pid={sorted(pids)}")
        return f"已关闭宿主（pid {', '.join(sorted(pids)) or '?'}）"
    except Exception as e:
        return f"关闭失败：{e}"


# ── 轮询线程 ─────────────────────────────────────────────────────────────
class Poller(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.paused = False
        self.stopped = False
        self.last_error = ""
        self.last_ok = 0.0
        self.rounds = 0

    def scan_once(self):
        try:
            if not core.acquire_lock():
                self.last_error = "上一轮还在跑，跳过"
                return
            try:
                asyncio.run(core.run(False, None))
                self.last_ok = time.time()
                self.rounds += 1
                self.last_error = ""
            finally:
                core.release_lock()
        except Exception as e:
            self.last_error = str(e)[:200]
            core.append_log(f"托盘轮询失败：{self.last_error}")

    def run(self):
        while not self.stopped:
            if not self.paused:
                self.scan_once()
            for _ in range(POLL_SECONDS * 2):
                if self.stopped:
                    return
                time.sleep(0.5)


poller = Poller()


# ── 窗口 ─────────────────────────────────────────────────────────────────
class App:
    def __init__(self, root, with_tray: bool):
        self.root = root
        self.with_tray = with_tray
        self.q: queue.Queue = queue.Queue()
        self.icon = None
        self.scanning = False

        root.title("刷B站 · 控制台")
        root.geometry("720x660")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        apply_window_icon(root)

        self.build()
        # 一启动就把宿主拉起来（否则值班轮不会跑）；--no-host 可以跳过
        if "--no-host" not in sys.argv:
            threading.Thread(target=self.ensure_host, daemon=True).start()
        poller.start()
        root.after(300, self.pump)
        root.after(200, self.refresh)

    # ── 布局 ────────────────────────────────────────────────────────────
    def build(self):
        pad = {"padx": 8, "pady": 3}

        # 状态条
        top = tk.Frame(self.root)
        top.pack(fill="x", **pad)
        self.lbl_state = tk.Label(top, text="启动中…", anchor="w", font=("Microsoft YaHei UI", 10))
        self.lbl_state.pack(side="left")
        self.lbl_scan = tk.Label(top, text="", anchor="e", fg="#666")
        self.lbl_scan.pack(side="right")

        # 行按钮
        bar = tk.Frame(self.root)
        bar.pack(fill="x", **pad)
        for text, act in (("立刻扫一次", "scan"), ("打开 DSH", "dsh"),
                          ("启动宿主", "starthost"), ("命令行", "term"),
                          ("暂停轮询", "toggle"), ("打开报告", "report"),
                          ("刷新", "refresh")):
            tk.Button(bar, text=text, width=10, command=lambda a=act: self.q.put(a)).pack(side="left", padx=2)

        # 待追问
        self.f_ask = tk.LabelFrame(self.root, text="待回答的追问")
        self.f_ask.pack(fill="x", **pad)
        self.lbl_ask = tk.Label(self.f_ask, text="（没有）", justify="left", anchor="w", wraplength=680)
        self.lbl_ask.pack(fill="x", padx=6, pady=2)
        self.f_ask_btns = tk.Frame(self.f_ask)
        self.f_ask_btns.pack(fill="x", padx=6, pady=2)

        # 关键词
        self.f_kw = tk.LabelFrame(self.root, text="搜索关键词（下一轮就用）")
        self.f_kw.pack(fill="both", expand=False, **pad)
        row = tk.Frame(self.f_kw)
        row.pack(fill="both", expand=True, padx=6, pady=2)
        self.lb_kw = tk.Listbox(row, height=5, exportselection=False)
        self.lb_kw.pack(side="left", fill="both", expand=True)
        side = tk.Frame(row)
        side.pack(side="left", padx=4)
        self.e_kw = tk.Entry(side, width=14)
        self.e_kw.pack(fill="x")
        tk.Button(side, text="添加", width=8, command=self.add_kw).pack(fill="x", pady=2)
        tk.Button(side, text="删所选", width=8, command=self.del_kw).pack(fill="x")

        # 屏蔽 + 闸门
        self.f_gate = tk.LabelFrame(self.root, text="投递闸门（命中真的发不出去）")
        self.f_gate.pack(fill="both", expand=False, **pad)
        g = tk.Frame(self.f_gate)
        g.pack(fill="both", expand=True, padx=6, pady=2)
        self.lb_mute = tk.Listbox(g, height=5, exportselection=False)
        self.lb_mute.pack(side="left", fill="both", expand=True)
        s2 = tk.Frame(g)
        s2.pack(side="left", padx=4)
        self.e_mute = tk.Entry(s2, width=14)
        self.e_mute.pack(fill="x")
        tk.Button(s2, text="屏蔽", width=8, command=self.add_mute).pack(fill="x", pady=2)
        tk.Button(s2, text="解除", width=8, command=self.del_mute).pack(fill="x")
        s3 = tk.Frame(g)
        s3.pack(side="left", padx=6)
        tk.Label(s3, text="时长上限(分钟, 0=不限)").pack(anchor="w")
        self.e_maxlen = tk.Entry(s3, width=8)
        self.e_maxlen.pack(anchor="w")
        tk.Label(s3, text="播放量下限(0=不限)").pack(anchor="w")
        self.e_minplay = tk.Entry(s3, width=8)
        self.e_minplay.pack(anchor="w")
        tk.Button(s3, text="应用闸门", width=10, command=self.apply_gate).pack(anchor="w", pady=2)

        # 台账
        self.f_led = tk.LabelFrame(self.root, text="最近台账")
        self.f_led.pack(fill="both", expand=True, **pad)
        self.txt = tk.Text(self.f_led, height=8, wrap="none")
        self.txt.pack(fill="both", expand=True, padx=6, pady=2)
        self.txt.configure(state="disabled")

    # ── 动作队列：托盘线程/按钮 → 主线程 ────────────────────────────────
    def pump(self):
        try:
            while True:
                act = self.q.get_nowait()
                self.handle(act)
        except queue.Empty:
            pass
        self.root.after(250, self.pump)

    def handle(self, act: str):
        if act == "show":
            self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        elif act == "scan":
            self.do_scan()
        elif act == "dsh":
            open_dsh()
            self.flash("已在浏览器打开 DSH（「跑一轮」按钮在那里）")
        elif act == "term":
            open_terminal()
            self.flash("已开一个命令行窗口（目录就是 bili-profile）")
        elif act == "starthost":
            threading.Thread(target=self.ensure_host, daemon=True).start()
        elif act == "stophost":
            self.flash(stop_host())
        elif act == "toggle":
            poller.paused = not poller.paused
            self.flash("轮询已暂停" if poller.paused else "轮询已恢复")
            self.refresh()
        elif act == "report":
            today = core.now_bj().strftime("%Y-%m-%d")
            f = core.OUT / f"{today}.md"
            target = f if f.exists() else core.OUT
            try:
                os.startfile(str(target))     # noqa: S606  本机打开文件
            except Exception as e:
                self.flash(f"打不开：{e}")
        elif act == "refresh":
            self.refresh()
        elif act == "quit":
            self.quit()

    def do_scan(self):
        if self.scanning:
            return
        self.scanning = True
        self.flash("扫描中…")

        def work():
            poller.scan_once()
            self.scanning = False
        threading.Thread(target=work, daemon=True).start()

    def ensure_host(self):
        self.flash("正在检查 DSH 宿主…")
        msg = start_host()
        self.flash(msg + ("　（本控制台启动的）" if _HOST["we_started"] else ""))
        core.append_log("托盘：" + msg)

    def flash(self, msg: str):
        self.lbl_state.configure(text=msg)

    # ── 编辑动作 ────────────────────────────────────────────────────────
    def add_kw(self):
        w = self.e_kw.get().strip()
        if not w:
            return
        core.patch_keywords(add=[w])
        self.e_kw.delete(0, "end")
        self.after_edit()

    def del_kw(self):
        sel = self.lb_kw.curselection()
        if not sel:
            return
        core.patch_keywords(remove=[self.lb_kw.get(sel[0])])
        self.after_edit()

    def add_mute(self):
        w = self.e_mute.get().strip()
        if not w:
            return
        core.patch_exclude(add=[w])
        self.e_mute.delete(0, "end")
        self.after_edit()

    def del_mute(self):
        sel = self.lb_mute.curselection()
        if not sel:
            return
        core.patch_exclude(remove=[self.lb_mute.get(sel[0])])
        self.after_edit()

    def apply_gate(self):
        try:
            mx = int(self.e_maxlen.get().strip() or 0)
            mp = int(self.e_minplay.get().strip() or 0)
        except ValueError:
            self.flash("时长/播放量要填整数")
            return
        core.patch_prefs(maxDurationMin=mx, minPlay=mp)
        self.after_edit()

    def after_edit(self):
        # 改完立刻把偏好渲染进章程，下一轮就生效
        try:
            subprocess.run([core.NODE, str(core.PREF)], capture_output=True, timeout=60,
                           creationflags=0x08000000 if os.name == "nt" else 0)
        except Exception:
            pass
        core.append_log("托盘：改了设置")
        self.refresh()

    # ── 回答追问 ────────────────────────────────────────────────────────
    def answer_ask(self, nums):
        q = core.read_ask()
        if not q:
            return
        reply = core.record_ask_answer(q, "nums", nums, False)
        core.append_log(f"托盘：回答了追问 {nums}")
        self.flash(reply.replace("\n", " ")[:80])
        self.refresh()

    # ── 刷新界面 ────────────────────────────────────────────────────────
    def refresh(self):
        try:
            self._refresh()
        except Exception as e:
            self.flash(f"刷新出错：{e}")
        self.root.after(3000, self.refresh)

    def _refresh(self):
        cfg = core.read_json(core.CFG, {}) or {}
        prefs = core.read_prefs()
        today = core.now_bj().strftime("%Y-%m-%d")
        picked = core.count_picked_today(today)
        age = core.last_scan_age()

        host = ("宿主在跑" + ("（本控制台起的）" if _HOST["we_started"] else "")) if host_up() \
            else "宿主没跑（值班轮不会自动触发）"
        poll_state = "已暂停" if poller.paused else f"每 {POLL_SECONDS} 秒"
        self.lbl_state.configure(
            text=f"今天 {picked} / {cfg.get('perDay', 0)}　关键词 {len(cfg.get('keywords') or [])}　"
                 f"轮询{poll_state}　{host}")
        self.lbl_scan.configure(text=f"上次扫私信 {age}" + (f"　⚠️ {poller.last_error}" if poller.last_error else ""))

        # 关键词
        kws = cfg.get("keywords") or []
        if list(self.lb_kw.get(0, "end")) != kws:
            self.lb_kw.delete(0, "end")
            for k in kws:
                self.lb_kw.insert("end", k)

        # 屏蔽词
        mut = cfg.get("excludeWords") or []
        if list(self.lb_mute.get(0, "end")) != mut:
            self.lb_mute.delete(0, "end")
            for k in mut:
                self.lb_mute.insert("end", k)

        if self.root.focus_get() is not self.e_maxlen:
            self.e_maxlen.delete(0, "end")
            self.e_maxlen.insert(0, str(prefs.get("maxDurationMin") or 0))
        if self.root.focus_get() is not self.e_minplay:
            self.e_minplay.delete(0, "end")
            self.e_minplay.insert(0, str(prefs.get("minPlay") or 0))

        # 待追问
        q = core.read_ask()
        for w in self.f_ask_btns.winfo_children():
            w.destroy()
        if not q:
            self.lbl_ask.configure(text="（没有）")
        else:
            tags, words = q.get("tags") or [], q.get("words") or []
            self.lbl_ask.configure(
                text=f"《{str(q.get('title'))[:34]}》{q.get('score')} 分　"
                     f"{'好在哪' if q.get('kind') == 'good' else '差在哪'}？点按钮（可多选后再点确认）")
            self._ask_sel = set()

            def toggle(n):
                self._ask_sel ^= {n}
                self.lbl_ask.configure(text=self.lbl_ask.cget("text").split("｜已选")[0] +
                                       f"｜已选 {sorted(self._ask_sel) or '无'}")

            col = 0
            for i, t in enumerate(tags, 1):
                tk.Button(self.f_ask_btns, text=f"{i} {t}", command=lambda n=i: toggle(n)).grid(row=0, column=col)
                col += 1
            for i, w in enumerate(words, len(tags) + 1):
                tk.Button(self.f_ask_btns, text=f"{i} {w}", command=lambda n=i: toggle(n)).grid(row=0, column=col)
                col += 1
            tk.Button(self.f_ask_btns, text="确认", bg="#dff0d8",
                      command=lambda: self.answer_ask(sorted(self._ask_sel))).grid(row=0, column=col + 1)

        # 台账
        rows = core.ledger()[-10:]
        lines = []
        for r in rows:
            s = r.get("score")
            tag = "文字" if s is None else (f"{s}分")
            lines.append(f"{str(r.get('date'))[5:]}  {tag:>4}  {str(r.get('title') or '')[:30]}")
        txt = "\n".join(reversed(lines)) or "（台账是空的）"
        if self.txt.get("1.0", "end").strip() != txt:
            self.txt.configure(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", txt)
            self.txt.configure(state="disabled")

    # ── 关窗 = 缩托盘 ───────────────────────────────────────────────────
    def on_close(self):
        if self.with_tray and self.icon is not None:
            self.root.withdraw()
            self.flash("已缩到托盘，轮询继续")
        else:
            self.quit()

    def quit(self):
        poller.stopped = True
        unmark_instance()
        try:
            if self.icon is not None:
                self.icon.stop()
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass


# ── 图标 ─────────────────────────────────────────────────────────────────
ICON_PNG = HERE / "图标.png"
ICON_ICO = HERE / "图标.ico"


def load_icon(size: int = 64):
    """图标：优先用 图标.png（抠掉白底的插画），没有就退回画一个。

    返回 (PIL.Image, tk.PhotoImage|None)。PhotoImage 只给 tkinter 用，
    必须挂在长生命周期对象上，否则会被 GC 掉、窗口图标变空白。
    """
    from PIL import Image

    if ICON_PNG.exists():
        try:
            img = Image.open(ICON_PNG).convert("RGBA")
            return img.resize((size, size), Image.LANCZOS)
        except Exception as e:
            core.append_log(f"读图标失败（用备用图标）：{e}")
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    from PIL import ImageDraw
    d = ImageDraw.Draw(img)
    k = size / 64
    d.ellipse((6 * k, 6 * k, 58 * k, 58 * k), fill=(0, 161, 214, 255))
    d.rectangle((26 * k, 18 * k, 38 * k, 46 * k), fill=(255, 255, 255, 255))
    d.rectangle((26 * k, 18 * k, 44 * k, 24 * k), fill=(255, 255, 255, 255))
    d.rectangle((26 * k, 29 * k, 44 * k, 35 * k), fill=(255, 255, 255, 255))
    d.rectangle((26 * k, 40 * k, 44 * k, 46 * k), fill=(255, 255, 255, 255))
    return img


def apply_window_icon(root) -> None:
    """任务栏 / 标题栏图标。tkinter 只认 PhotoImage(GIF/PNG/PPM)。"""
    try:
        import tkinter as tk
        if ICON_PNG.exists():
            photo = tk.PhotoImage(file=str(ICON_PNG))
            root.iconphoto(True, photo)
            root._bili_icon_photo = photo        # 留住引用，否则图标会变空白
    except Exception as e:
        core.append_log(f"窗口图标没设上：{e}")


# ── 托盘 ─────────────────────────────────────────────────────────────────
def start_tray(app: App):
    try:
        import pystray
    except Exception as e:
        print("托盘库没装好（pip install pystray pillow）：", e)
        return None

    img = load_icon(64)

    menu = pystray.Menu(
        pystray.MenuItem("显示窗口", lambda: app.q.put("show"), default=True),
        pystray.MenuItem("立刻扫一次", lambda: app.q.put("scan")),
        pystray.MenuItem("打开 DSH 网页", lambda: app.q.put("dsh")),
        pystray.MenuItem("打开命令行", lambda: app.q.put("term")),
        pystray.MenuItem("启动宿主（dsh web）", lambda: app.q.put("starthost")),
        pystray.MenuItem("关闭宿主", lambda: app.q.put("stophost")),
        pystray.MenuItem("暂停/继续轮询", lambda: app.q.put("toggle")),
        pystray.MenuItem("打开报告", lambda: app.q.put("report")),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", lambda: app.q.put("quit")),
    )
    icon = pystray.Icon("bili-duty", img, "刷B站 · 控制台", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


# ── 自测：不开界面，只打印界面会显示什么 ─────────────────────────────────
def selftest():
    cfg = core.read_json(core.CFG, {}) or {}
    prefs = core.read_prefs()
    today = core.now_bj().strftime("%Y-%m-%d")
    print("DUTY      :", core.DUTY)
    print("今天挑    :", core.count_picked_today(today), "/", cfg.get("perDay", 0))
    print("上次扫    :", core.last_scan_age())
    print("关键词    :", " · ".join(cfg.get("keywords") or []))
    print("屏蔽词    :", " · ".join(cfg.get("excludeWords") or []))
    print("闸门      : 时长上限", prefs.get("maxDurationMin") or 0, "分钟 | 播放量下限", prefs.get("minPlay") or 0)
    q = core.read_ask()
    if q:
        print("待追问    :", f"《{str(q.get('title'))[:30]}》{q.get('score')} 分")
        print("  选项    :", " ".join((q.get("tags") or []) + (q.get("words") or [])))
    else:
        print("待追问    : （没有）")
    print("DSH 宿主  :", "在跑" if host_up() else "没跑")
    print("台账条数  :", len(core.ledger()))
    print("\n界面能启动、数据都能读到 ✓")


def main():
    relaunch_without_console()          # 别让黑框控制台跟着常驻
    if "--selftest" in sys.argv:
        selftest()
        return
    if another_instance():
        core.append_log("托盘控制台：已经有一个在跑了，这次直接退出")
        return
    hide_own_console()                  # 万一是带黑框起的，藏掉它
    mark_instance()
    global tk
    import tkinter as tk
    with_tray = "--no-tray" not in sys.argv
    root = tk.Tk()
    app = App(root, with_tray)
    if with_tray:
        app.icon = start_tray(app)
        if app.icon is None:
            app.with_tray = False
    root.mainloop()


if __name__ == "__main__":
    # pythonw 启动时**没有控制台**，崩了什么提示都看不到 ⇒ 必须自己留痕
    try:
        main()
    except SystemExit:                       # 换成 pythonw 重开自己时的正常退出，不是崩溃
        pass
    except BaseException as _e:
        import traceback as _tb
        try:
            core.append_log("托盘控制台崩溃：" + str(_e) + "｜"
                            + _tb.format_exc(limit=6).replace("\n", " ")[:600])
        except Exception:
            pass
        raise
