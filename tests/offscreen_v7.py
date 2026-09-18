# -*- coding: utf-8 -*-
"""V7 离屏自测：任务栏隐藏 + 托盘菜单 + 开机自启（offscreen 平台，无真实 UI/托盘）。

注册表用真机 HKCU（用户级，安全），测试后恢复原值。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\Mings_Project\key-usage-widget")

import winreg  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QSystemTrayIcon  # noqa: E402

from keymon import autostart  # noqa: E402
from keymon.ui_qt import MainWindow, TrayController  # noqa: E402

RUN_KEY = autostart.RUN_KEY
VALUE_NAME = autostart.VALUE_NAME

_failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} {name} {detail}")
    if not cond:
        _failures.append(name)


def main():
    app = QApplication([])

    win = MainWindow()
    win.show()

    # ---- V7-M1：主窗 Qt.Tool 隐藏任务栏 ----
    check("1 主窗flags含Qt.Tool", bool(win.windowFlags() & Qt.Tool),
          f"flags={win.windowFlags()}")
    check("2 主窗flags仍含置顶+无边框",
          bool(win.windowFlags() & Qt.WindowStaysOnTopHint)
          and bool(win.windowFlags() & Qt.FramelessWindowHint))

    # ---- V7-M2：托盘 + 右键菜单结构（直接构造，不依赖 offscreen 是否真有托盘） ----
    tray = TrayController(win)
    win._tray = tray
    actions = [a for a in tray._menu.actions() if not a.isSeparator()]
    check("3 托盘菜单3项(显隐/自启/退出)", len(actions) == 3, f"got {len(actions)}")
    check("4 自启项可勾选", tray._autostart_action.isCheckable())
    check("5 托盘tooltip", tray._tray.toolTip() == "Key 用量面板")
    check("6 托盘有图标", not tray._tray.icon().isNull())

    # 显隐切换
    check("7 初始可见", win.isVisible())
    tray._toggle_window()
    check("8 切换后隐藏", not win.isVisible())
    tray._sync_toggle_text()  # 生产环境由 aboutToShow 触发，此处手动同步
    check("9 菜单文本切为显示面板", tray._toggle_action.text() == "显示面板")
    tray._sync_toggle_text()
    tray._toggle_window()
    check("10 再切回显示", win.isVisible())

    # 圆球数据 → 托盘图标联动（不 crash 即可）
    tray.update_orb(60, win._remaining_color(0.6))
    check("11 托盘图标联动更新", not tray._tray.icon().isNull())

    # v10 语义：圆球显示剩余量（与表格一致）
    fake_provider = {"provider_type": "kimi"}
    pct, color, text = win._orb_value(fake_provider, {"h5_remaining": 0.99})
    check("11b 圆球显示剩余量", pct == 99 and text == "99%", f"pct={pct} text={text}")
    pct2, color2, _ = win._orb_value(fake_provider, {"h5_remaining": 0.05})
    from keymon.ui_qt import RED as _RED, GREEN as _GREEN
    check("11c 剩余5%显示红色", pct2 == 5 and color2 == _RED, f"pct={pct2}")
    check("11d 剩余99%显示绿色", color == _GREEN)

    # ---- V7-M3：autostart 注册表读写（真机 HKCU，测后恢复） ----
    orig = None
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            orig, _ = winreg.QueryValueEx(k, VALUE_NAME)
    except OSError:
        pass

    try:
        cmd = autostart.build_command()
        check("12 启动命令含pythonw与app.pyw", "pythonw" in cmd and "app.pyw" in cmd, cmd)

        autostart.enable()
        check("13 enable后is_enabled", autostart.is_enabled())
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            val, typ = winreg.QueryValueEx(k, VALUE_NAME)
        check("14 注册表值=build_command", val == cmd and typ == winreg.REG_SZ, val)

        # 托盘勾选状态与注册表同步
        tray._autostart_action.setChecked(True)
        check("15 勾选同步注册表", autostart.is_enabled())
        tray._autostart_action.setChecked(False)
        check("16 取消勾选同步注册表", not autostart.is_enabled())

        autostart.disable()
        check("17 disable后is_enabled为False", not autostart.is_enabled())
    finally:
        if orig is not None:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.SetValueEx(k, VALUE_NAME, 0, winreg.REG_SZ, orig)
        else:
            autostart.disable()

    check("18 环境托盘可用性探测不crash",
          QSystemTrayIcon.isSystemTrayAvailable() in (True, False))

    print("\n" + ("FAILED: " + ", ".join(_failures) if _failures else "ALL PASSED"))
    sys.exit(1 if _failures else 0)


if __name__ == "__main__":
    main()
