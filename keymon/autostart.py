# -*- coding: utf-8 -*-
"""开机自启（跨平台）：
- Windows：HKCU Run 注册表（用户级，免管理员）；
- macOS：LaunchAgents plist（~/Library/LaunchAgents/，登录时加载）。

各平台自启存储是该平台的事实来源：托盘勾选状态实时读取，不在 config.json 另存一份。
"""
import os
import sys

if sys.platform == "win32":
    import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "key-usage-widget"

# macOS LaunchAgents
PLIST_LABEL = "com.key-usage-widget"
PLIST_PATH = os.path.join(
    os.path.expanduser("~"), "Library", "LaunchAgents", f"{PLIST_LABEL}.plist"
)


def _app_entry_path():
    """入口脚本 app.pyw 的绝对路径（keymon 包所在项目根）。"""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.pyw"))


def _pythonw():
    """定位无控制台黑框的解释器（Windows 为 pythonw.exe；mac 无此概念，直接用当前解释器）。"""
    exe = sys.executable
    base = os.path.basename(exe).lower()
    if base.startswith("python") and base.endswith(".exe") and "pythonw" not in base:
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(candidate):
            return candidate
    return exe


def build_command():
    """开机启动命令行（Windows 用）。冻结（exe 打包）时直接指向 exe。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{_pythonw()}" "{_app_entry_path()}"'


def _mac_program_args():
    """macOS plist 的 ProgramArguments：冻结 .app 时直接指向可执行文件。"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, _app_entry_path()]


_PLIST_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
{array_items}
    </array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""


def is_enabled():
    """是否存在本应用的启动项。"""
    if sys.platform == "darwin":
        return os.path.exists(PLIST_PATH)
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, VALUE_NAME)
        return bool(val)
    except OSError:
        return False


def enable():
    """写入启动项。"""
    if sys.platform == "darwin":
        os.makedirs(os.path.dirname(PLIST_PATH), exist_ok=True)
        items = "\n".join(f"        <string>{a}</string>" for a in _mac_program_args())
        with open(PLIST_PATH, "w", encoding="utf-8") as f:
            f.write(_PLIST_TEMPLATE.format(label=PLIST_LABEL, array_items=items))
        return
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, build_command())


def disable():
    """删除启动项；不存在时静默通过。"""
    if sys.platform == "darwin":
        try:
            os.remove(PLIST_PATH)
        except FileNotFoundError:
            pass
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
    except FileNotFoundError:
        pass
