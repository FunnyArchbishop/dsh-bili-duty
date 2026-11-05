' 刷B站控制台 · 无窗口启动器（示例 —— 复制成 console-launch.vbs 再改路径）
' 为什么不用 pythonw.exe：uv 建的 venv 里 pythonw.exe 的 PE subsystem 还是 3（控制台），
' 弹不弹窗口跟文件名没关系。用 WshShell.Run 的窗口样式 0 才对任何控制台程序都有效。
' 0 = 窗口隐藏；True = 等它跑完（这样计划任务的历史里能看到耗时）
Option Explicit
Dim sh, cmd, i, extra
Set sh = CreateObject("WScript.Shell")
cmd = """<换成你的 python.exe>""" & " " & """<换成 私信控制台.py 的路径>"""
extra = ""
For i = 0 To WScript.Arguments.Count - 1
  extra = extra & " """ & WScript.Arguments(i) & """"
Next
cmd = cmd & extra
sh.Run cmd, 0, True
