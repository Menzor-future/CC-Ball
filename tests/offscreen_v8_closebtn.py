# -*- coding: utf-8 -*-
"""V8 离屏复现+回归：关闭小球"回到圆球后又闪出再消失"。

根因假设（v7 主窗改 Qt.Tool 后事件时序变化）：
收回动画结束的 finished 处理（hide+复位）先执行，Qt 补发的合成 Enter 排在其后，
到达时动画已不在运行 → V6-M11 的"运行中"守卫失效 → 误判 hover 重启弹出；
用户继续移开鼠标 → 200ms 倒计时 → 再次收回消失（主观即"闪出来又消失"）。

PASS A/B/C：回归 V6-M11（运行中合成 Enter 不打断收回 / 真实 hover 改向）。
PASS D：【复现】收回完成后、鼠标未动，合成 Enter 不得弹出（修复前此处 FAIL）。
PASS E：真实鼠标移动后再 Enter → 正常弹出。
"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, r"D:\Mings_Project\key-usage-widget")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from keymon.ui_qt import MainWindow  # noqa: E402

_failures = []


def check(name, cond, detail=""):
    print(f"{'PASS' if cond else 'FAIL'} {name} {detail}")
    if not cond:
        _failures.append(name)


def pump(app, ms):
    """offscreen 下动画走真实时钟：轮转事件循环直到耗时 ms。"""
    deadline = time.monotonic() + ms / 1000.0
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def send_enter(win):
    QApplication.sendEvent(win, QEvent(QEvent.Enter))


def send_move(win):
    e = QMouseEvent(QEvent.MouseMove, win.rect().center(), Qt.NoButton,
                    Qt.NoButton, Qt.NoModifier)
    QApplication.sendEvent(win, e)


def main():
    app = QApplication([])
    win = MainWindow()
    win.show()
    btn = win.close_btn

    # 先完整弹出（模拟 hover 后按钮到位）
    win._start_close_pop_in()
    pump(app, 600)
    check("A0 弹出完成", btn.isVisible() and win._btn_parent_rect() == win._close_full_rect,
          f"rect={win._btn_parent_rect()}")

    # ---- PASS A：收回运行中，合成 Enter 不打断（V6-M11 回归） ----
    win._start_close_pop_out()
    pump(app, 100)  # 收回进行中
    check("A 收回运行中", win._close_pop_anim.state() == QAbstractAnimation_running(win),
          f"showing={win._close_pop_showing}")
    send_enter(win)
    pump(app, 50)
    check("B 运行中合成Enter不改向", win._close_pop_showing is False,
          f"showing={win._close_pop_showing}")

    # ---- PASS C：收回运行中，真实 hover 按钮（eventFilter Enter）改向弹出 ----
    win.eventFilter(btn, QEvent(QEvent.Enter))
    pump(app, 50)
    check("C 真实hover改向弹出", win._close_pop_showing is True)

    # 让它弹完，再正常收回一次
    pump(app, 600)
    win._start_close_pop_out()
    pump(app, 600)  # 收回动画 350ms + 余量
    check("D0 收回完成已隐藏", not btn.isVisible())

    # ---- PASS D：【复现点】收回完成后、鼠标未动，补发的合成 Enter 不得弹出 ----
    send_enter(win)
    pump(app, 80)
    pop_in_after_done = (btn.isVisible()
                         or win._close_pop_anim.state() == QAbstractAnimation_running(win))
    check("D 完成后合成Enter不弹出", not pop_in_after_done,
          f"visible={btn.isVisible()} showing={win._close_pop_showing}")

    # ---- PASS E：真实移动鼠标后再 Enter → 正常弹出 ----
    send_move(win)
    send_enter(win)
    pump(app, 600)
    check("E 真实移动后正常弹出", btn.isVisible()
          and win._btn_parent_rect() == win._close_full_rect,
          f"visible={btn.isVisible()} rect={win._btn_parent_rect()}")

    print("\n" + ("FAILED: " + ", ".join(_failures) if _failures else "ALL PASSED"))
    sys.exit(1 if _failures else 0)


def QAbstractAnimation_running(win):
    from PySide6.QtCore import QAbstractAnimation
    return QAbstractAnimation.Running


if __name__ == "__main__":
    main()
