' 刷B站控制台 · 静默启动器模板
' ---------------------------------------------------------------------------
' 为什么需要这么一个 vbs：
'   这个 uv 造的 venv 里 python.exe 和 pythonw.exe **是同一份复制**
'   （都是 console 子系统，各 45568 字节），直接启动任何一个都会带一个黑框控制台窗口。
'   "换成 pythonw.exe"解决不了 —— 试过。
'   wscript 的 Shell.Run(cmd, 0, ...)（window style 0 = 隐藏）是唯一真不给窗口的路径，
'   计划任务 DSH-BiliScoring 用的 console-launch.vbs 也是这个路子。
'
' 用法：由 patches/应用补丁.py 把 @PYTHONW@ / @SCRIPT@ 换成本机路径后，
'       写成 **UTF-16 LE + BOM** 的 启动控制台.vbs（wscript 读 UTF-8 会弄坏中文路径），
'       再把桌面快捷方式指到  wscript.exe "<这个 vbs>"。
' ---------------------------------------------------------------------------
Option Explicit
Dim sh
Set sh = CreateObject("WScript.Shell")
sh.Run """" & "@PYTHONW@" & """ """ & "@SCRIPT@" & """", 0, False
