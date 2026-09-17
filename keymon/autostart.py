# -*- coding: utf-8 -*-
"""开机自启：HKCU Run 注册表读写（用户级，免管理员，程序可自管理）。

注册表是唯一事实来源：托盘勾选状态实时读注册表，不在 config.json 里另存一份。
"""
import os
import sys

import winreg  # noqa: F401  本项目仅支持 Windows

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "key-usage-widget"


def _app_entry_path():
    """入口脚本 app.pyw 的绝对路径（keymon 包所在项目根）。"""
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app.pyw"))


def _pythonw():
    """定位无控制台黑框的 pythonw.exe（与当前解释器同目录）。"""
    exe = sys.executable
    base = os.path.basename(exe).lower()
    if base.startswith("python") and base.endswith(".exe") and "pythonw" not in base:
        candidate = os.path.join(os.path.dirname(exe), "pythonw.exe")
        if os.path.exists(candidate):
            return candidate
    return exe


def build_command():
    """开机启动命令行。冻结（exe 打包）时直接指向 exe。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    return f'"{_pythonw()}" "{_app_entry_path()}"'


def is_enabled():
    """注册表里是否存在本应用的启动项。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, _ = winreg.QueryValueEx(k, VALUE_NAME)
        return bool(val)
    except OSError:
        return False


def enable():
    """写入启动项（命令 = pythonw + app.pyw，双击同款无控制台）。"""
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
        winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, build_command())


def disable():
    """删除启动项；不存在时静默通过。"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, VALUE_NAME)
    except FileNotFoundError:
        pass
