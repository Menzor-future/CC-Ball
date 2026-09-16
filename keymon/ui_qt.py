# -*- coding: utf-8 -*-
"""PySide6 悬浮窗 UI：圆球仪表盘 + 展开表格。"""
import datetime as dt
import os
import sys

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, QTimer, Signal, QObject,
    QRectF, QPoint, QSize,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QBrush, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QSizePolicy, QSpacerItem, QVBoxLayout, QWidget,
)

from .config import (
    LOW_BALANCE_CNY,
    REFRESH_INTERVAL_S,
    USER_CONFIG_PATH,
    load_user_config,
    save_user_config,
)
from .ccdb import read_providers
from .quota import QuotaCache, fetch_all

# 诊断日志路径
_UI_LOG_PATH = os.path.join(os.path.dirname(USER_CONFIG_PATH), "ui.log")


def _ui_log(msg):
    try:
        with open(_UI_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.now():%H:%M:%S.%f} {msg}\n")
    except Exception:
        pass


def _reset_ui_log():
    try:
        with open(_UI_LOG_PATH, "w", encoding="utf-8") as f:
            f.write("")
    except Exception:
        pass


# 配色
BG = QColor(26, 26, 32, 220)          # 半透黑背景
BG_CURRENT = QColor(42, 37, 48, 255)
TEXT = QColor(230, 230, 234, 255)
TEXT_DIM = QColor(139, 139, 149, 255)
ACCENT = QColor(88, 166, 255, 255)
GREEN = QColor(63, 185, 80, 255)
ORANGE = QColor(210, 153, 34, 255)
RED = QColor(248, 81, 73, 255)
HEADER_BG = QColor(37, 37, 44, 255)
GRID = QColor(53, 53, 61, 255)

# 圆球配色
ORB_FILL = QColor(26, 26, 32, 200)     # 圆球内部填充（半透黑）
ORB_TRACK = QColor(42, 42, 53, 255)    # 进度环轨道

COLS = ["账号名", "模型", "5h", "7day"]
COL_WIDTHS = [110, 120, 105, 105]

ORB_SIZE = 120
ORB_PAD = 8
ORB_STROKE = 8


class OrbWidget(QWidget):
    """圆形仪表盘，显示当前 provider 的 5h 已用量。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(ORB_SIZE, ORB_SIZE)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)

        self._pct = None
        self._color = TEXT_DIM
        self._text = "--"

        # 拖动
        self._drag_pos = QPoint()

    def set_value(self, pct, color, text):
        self._pct = pct
        self._color = color
        self._text = text
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r = min(w, h) / 2 - ORB_PAD

        # 圆球内部填充（半透黑）
        fill_path = QPainterPath()
        fill_path.addEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))
        painter.fillPath(fill_path, QBrush(ORB_FILL))

        # 背景进度环（深灰透黑）
        track_pen = QPen(ORB_TRACK, ORB_STROKE)
        track_pen.setCapStyle(Qt.RoundCap)
        painter.setPen(track_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # 彩色进度弧
        if self._pct is not None:
            arc_pen = QPen(self._color, ORB_STROKE)
            arc_pen.setCapStyle(Qt.RoundCap)
            painter.setPen(arc_pen)
            # Qt 的 arc 从 3 点钟方向开始，逆时针；我们想要从 12 点钟方向顺时针
            start_angle = 90 * 16  # 90 度 = 12 点钟方向
            span_angle = -int(self._pct * 3.6 * 16)  # 负数表示顺时针
            painter.drawArc(QRectF(cx - r, cy - r, r * 2, r * 2), start_angle, span_angle)

        # 百分比文字
        painter.setPen(QPen(TEXT))
        font = QFont("Microsoft YaHei UI", 14, QFont.Bold)
        painter.setFont(font)
        painter.drawText(QRectF(cx - r, cy - r, r * 2, r * 2), Qt.AlignCenter, self._text)

        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._pressed = True

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and getattr(self, '_pressed', False):
            # 如果移动距离很小，视为点击
            if (event.globalPosition().toPoint() - self._drag_pos - self.frameGeometry().topLeft()).manhattanLength() < 4:
                self.clicked.emit()
            self._pressed = False


class TableWidget(QFrame):
    """展开的方形表格。"""

    close_clicked = Signal()
    refresh_clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self._setup_ui()
        self._rows = []

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        # 表格容器
        self.table_frame = QFrame()
        self.table_frame.setStyleSheet(f"background-color: {GRID.name()}; border-radius: 4px;")
        table_layout = QGridLayout(self.table_frame)
        table_layout.setSpacing(1)
        table_layout.setContentsMargins(1, 1, 1, 1)

        # 表头
        for col, (label, width) in enumerate(zip(COLS, COL_WIDTHS)):
            header = QLabel(label)
            header.setFixedSize(width, 26)
            header.setStyleSheet(
                f"color: {TEXT_DIM.name()}; background-color: {HEADER_BG.name()};"
                f" padding-left: 6px; font-size: 11px; border-radius: 0px;"
            )
            table_layout.addWidget(header, 0, col)

        layout.addWidget(self.table_frame)

        # footer
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)

        self.refresh_btn = QLabel("⟳")
        self.refresh_btn.setStyleSheet(f"color: {ACCENT.name()}; font-size: 13px; padding: 2px;")
        self.refresh_btn.setCursor(Qt.PointingHandCursor)
        self.refresh_btn.mousePressEvent = lambda e: self.refresh_clicked.emit()
        footer.addWidget(self.refresh_btn)

        self.updated_label = QLabel("")
        self.updated_label.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 10px; padding: 2px;")
        footer.addWidget(self.updated_label)

        footer.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))

        self.close_btn = QLabel("✕")
        self.close_btn.setStyleSheet(f"color: {TEXT_DIM.name()}; font-size: 13px; padding: 2px;")
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.mousePressEvent = lambda e: self.close_clicked.emit()
        footer.addWidget(self.close_btn)

        layout.addLayout(footer)

    def render(self, providers, results, error):
        # 清除旧行
        for row_widgets in self._rows:
            for w in row_widgets:
                w.setParent(None)
        self._rows.clear()

        if error:
            self._render_error(error)
            return
        if not providers:
            self._render_error("未找到 provider 配置")
            return

        table_layout = self.table_frame.layout()

        for row_idx, provider in enumerate(providers, start=1):
            self._render_row(table_layout, row_idx, provider, results.get(provider["id"], {}))

        self.updated_label.setText(f"更新于 {dt.datetime.now().strftime('%H:%M:%S')}")

    def _render_row(self, layout, row_idx, provider, res):
        is_current = provider["is_current"]
        bg = BG_CURRENT if is_current else BG
        font_weight = "bold" if is_current else "normal"

        ptype = provider["provider_type"]
        account_name = provider["name"]
        if ptype == "kimi":
            account_name = res.get("account_name") or provider["name"]
        elif ptype == "deepseek":
            account_name = "DeepSeek"
        elif ptype == "anthropic":
            account_name = "Claude"

        widgets = []

        # 账号名
        w = QLabel(account_name)
        w.setFixedSize(COL_WIDTHS[0], 26)
        w.setStyleSheet(
            f"color: {TEXT.name()}; background-color: {bg.name()};"
            f" padding-left: 6px; font-size: 12px; font-weight: {font_weight};"
        )
        layout.addWidget(w, row_idx, 0)
        widgets.append(w)

        # 模型
        w = QLabel(provider["model"])
        w.setFixedSize(COL_WIDTHS[1], 26)
        w.setStyleSheet(
            f"color: {TEXT_DIM.name()}; background-color: {bg.name()};"
            f" padding-left: 6px; font-size: 12px; font-weight: {font_weight};"
        )
        layout.addWidget(w, row_idx, 1)
        widgets.append(w)

        if "error" in res:
            w = QLabel(res["error"])
            w.setFixedSize(COL_WIDTHS[2], 26)
            w.setStyleSheet(
                f"color: {RED.name()}; background-color: {bg.name()};"
                f" padding-right: 6px; font-size: 12px; font-weight: {font_weight};"
            )
            layout.addWidget(w, row_idx, 2)
            widgets.append(w)

            w = QLabel("")
            w.setFixedSize(COL_WIDTHS[3], 26)
            w.setStyleSheet(f"background-color: {bg.name()};")
            layout.addWidget(w, row_idx, 3)
            widgets.append(w)
        elif ptype == "deepseek":
            try:
                bal = float(res.get("balance", "0"))
                color = ORANGE if bal < LOW_BALANCE_CNY else GREEN
            except ValueError:
                bal = 0.0
                color = TEXT
            text = f"余额 ¥{res.get('balance', '--')}"
            w = QLabel(text)
            w.setFixedSize(COL_WIDTHS[2] + COL_WIDTHS[3] + 2, 26)
            w.setStyleSheet(
                f"color: {color.name()}; background-color: {bg.name()};"
                f" padding-right: 6px; font-size: 12px; font-weight: {font_weight};"
            )
            w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(w, row_idx, 2, 1, 2)
            widgets.append(w)
        else:
            h5 = res.get("h5_remaining")
            d7 = res.get("d7_remaining")

            h5_text = self._fmt_pct(h5, res.get("h5_reset"))
            h5_color = self._pct_color(h5)
            w = QLabel(h5_text)
            w.setFixedSize(COL_WIDTHS[2], 26)
            w.setStyleSheet(
                f"color: {h5_color.name()}; background-color: {bg.name()};"
                f" padding-right: 6px; font-size: 12px; font-weight: {font_weight};"
            )
            w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(w, row_idx, 2)
            widgets.append(w)

            d7_text = self._fmt_pct(d7, res.get("d7_reset"), compact=True)
            d7_color = self._pct_color(d7)
            w = QLabel(d7_text)
            w.setFixedSize(COL_WIDTHS[3], 26)
            w.setStyleSheet(
                f"color: {d7_color.name()}; background-color: {bg.name()};"
                f" padding-right: 6px; font-size: 12px; font-weight: {font_weight};"
            )
            w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(w, row_idx, 3)
            widgets.append(w)

        self._rows.append(widgets)

    def _render_error(self, message):
        table_layout = self.table_frame.layout()
        w = QLabel(message)
        w.setFixedSize(sum(COL_WIDTHS) + 6, 60)
        w.setStyleSheet(
            f"color: {RED.name()}; background-color: {BG.name()};"
            f" font-size: 12px; padding: 8px;"
        )
        w.setAlignment(Qt.AlignCenter)
        table_layout.addWidget(w, 1, 0, 1, 4)
        self._rows.append([w])

    @staticmethod
    def _fmt_pct(value, reset_time=None, compact=False):
        pct = TableWidget._fmt_pct_raw(value)
        if value is None or not reset_time:
            return pct
        return f"{pct} ({TableWidget._fmt_countdown(reset_time, compact=compact)})"

    @staticmethod
    def _fmt_pct_raw(value):
        if value is None:
            return "N/A"
        return f"{max(0.0, min(1.0, value)) * 100:.0f}%"

    @staticmethod
    def _fmt_countdown(reset_time, compact=False):
        if not reset_time:
            return "-"
        try:
            ts = reset_time.replace("Z", "+00:00")
            reset = dt.datetime.fromisoformat(ts)
            now = dt.datetime.now(dt.timezone.utc)
            delta = reset - now
            if delta.total_seconds() <= 0:
                return "expired"
            total_seconds = int(delta.total_seconds())
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            if compact:
                if days > 0:
                    return f"{days}d"
                if hours > 0:
                    return f"{hours}h"
                return f"{minutes}m"
            if days > 0:
                return f"{days}d{hours}h"
            if hours > 0:
                return f"{hours}h{minutes}m"
            return f"{minutes}m"
        except Exception:
            return "-"

    @staticmethod
    def _pct_color(value):
        if value is None:
            return TEXT_DIM
        if value < 0.2:
            return RED
        if value < 0.5:
            return ORANGE
        return GREEN


class MainWindow(QMainWindow):
    """主窗口：根据模式显示圆球或表格。"""

    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.providers = []
        self.results = {}
        self.error = None
        self.current_provider = None
        self.cache = QuotaCache(ttl_s=60)
        self._mode = "orb"

        # 圆球
        self.orb = OrbWidget(self)
        self.orb.clicked.connect(self._expand)
        self.orb.show()

        # 表格（初始隐藏）
        self.table = TableWidget(self)
        self.table.close_clicked.connect(self._collapse)
        self.table.refresh_clicked.connect(self.refresh)
        self.table.hide()

        # 自动刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_INTERVAL_S * 1000)

        self._restore_state()
        self.refresh()

    def _restore_state(self):
        cfg = load_user_config()
        geo = cfg.get("geometry")
        x, y = 80, 80
        if geo:
            try:
                parts = geo.split("+", 1)
                if len(parts) == 2:
                    x, y = map(int, parts[1].split("+", 1))
            except Exception:
                pass
        self.move(x, y)

    def _save_state(self):
        cfg = load_user_config()
        cfg["geometry"] = f"{self.x()}+{self.y()}"
        cfg["mode"] = self._mode
        save_user_config(cfg)

    def refresh(self):
        data = read_providers()
        providers = data.get("providers", [])
        error = data.get("error")
        results = fetch_all(providers, cache=self.cache) if not error and providers else {}

        self.providers = providers
        self.results = results
        self.error = error
        self.current_provider = next((p for p in providers if p["is_current"]), providers[0] if providers else None)

        self._update_orb()
        if self._mode == "table":
            self._render_table()

    def _update_orb(self):
        provider = self.current_provider
        res = self.results.get(provider["id"], {}) if provider else {}
        pct, color, text = self._orb_value(provider, res)
        self.orb.set_value(pct, color, text)

    def _orb_value(self, provider, res):
        if not provider:
            return None, TEXT_DIM, "--"
        ptype = provider.get("provider_type", "custom")
        if ptype == "kimi":
            remaining = res.get("h5_remaining")
            if remaining is None:
                return None, TEXT_DIM, "N/A"
            used = max(0.0, min(1.0, 1.0 - remaining))
            pct = int(used * 100)
            return pct, self._used_color(used), f"{pct}%"
        return None, TEXT_DIM, "N/A"

    @staticmethod
    def _used_color(used):
        if used >= 0.8:
            return RED
        if used >= 0.5:
            return ORANGE
        return GREEN

    def _render_table(self):
        self.table.render(self.providers, self.results, self.error)
        # 调整窗口大小
        row_count = len(self.providers) if self.providers else 1
        width = sum(COL_WIDTHS) + 20
        height = 28 + row_count * 28 + 40
        self.resize(width, height)
        self.table.resize(width, height)

    def _expand(self):
        self._mode = "table"
        self.orb.hide()
        self.table.show()
        self._render_table()
        self._save_state()

    def _collapse(self):
        self._mode = "orb"
        self.table.hide()
        self.orb.show()
        self.resize(ORB_SIZE, ORB_SIZE)
        self._save_state()

    def closeEvent(self, event):
        self._save_state()
        super().closeEvent(event)


def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(True)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
