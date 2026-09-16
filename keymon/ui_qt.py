# -*- coding: utf-8 -*-
"""PySide6 悬浮窗 UI：圆球仪表盘 + 展开表格。"""
import datetime as dt
import math
import os
import sys

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QParallelAnimationGroup,
    QPropertyAnimation, Qt, QTimer,
    Signal, QObject, QRectF, QPoint, QSize, Property,
    QSequentialAnimationGroup,
)
from PySide6.QtGui import (
    QColor, QFont, QPainter, QPainterPath, QPen, QBrush, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QMainWindow, QSizePolicy, QSpacerItem, QVBoxLayout, QWidget,
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

ORB_SIZE = 100
ORB_PAD = 8
ORB_STROKE = 7


class OrbWidget(QWidget):
    """已废弃：圆球由 MainWindow.paintEvent 统一绘制，保证变形动画是单一整体。

    保留此类仅为兼容旧引用，不再实例化。
    """

    pass


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
        self._row_kinds = None

    @staticmethod
    def _row_kind(provider, res):
        if "error" in res:
            return "error"
        if provider["provider_type"] == "deepseek":
            return "deepseek"
        return "std"

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
        if error:
            self._render_error(error)
            return
        if not providers:
            self._render_error("未找到 provider 配置")
            return

        # 行结构（每行类型）变化时才重建 widget，否则复用只更新文本/样式
        kinds = [self._row_kind(p, results.get(p["id"], {})) for p in providers]
        if kinds != self._row_kinds:
            self._clear_rows()
            table_layout = self.table_frame.layout()
            for row_idx, (provider, kind) in enumerate(zip(providers, kinds), start=1):
                self._build_row(table_layout, row_idx, kind)
            self._row_kinds = kinds

        for row_idx, provider in enumerate(providers):
            self._update_row(row_idx, provider, results.get(provider["id"], {}))

        self.updated_label.setText(f"更新于 {dt.datetime.now().strftime('%H:%M:%S')}")

    def _clear_rows(self):
        for row_widgets in self._rows:
            for w in row_widgets:
                w.setParent(None)
        self._rows.clear()
        self._row_kinds = None

    def _build_row(self, layout, row_idx, kind):
        widgets = []
        if kind == "deepseek":
            for col in (0, 1):
                w = QLabel()
                w.setFixedSize(COL_WIDTHS[col], 26)
                layout.addWidget(w, row_idx, col)
                widgets.append(w)
            w = QLabel()
            w.setFixedSize(COL_WIDTHS[2] + COL_WIDTHS[3] + 2, 26)
            w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            layout.addWidget(w, row_idx, 2, 1, 2)
            widgets.append(w)
        else:
            for col in range(4):
                w = QLabel()
                w.setFixedSize(COL_WIDTHS[col], 26)
                if col >= 2:
                    w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                layout.addWidget(w, row_idx, col)
                widgets.append(w)
        self._rows.append(widgets)

    def _update_row(self, row_idx, provider, res):
        widgets = self._rows[row_idx]
        kind = self._row_kinds[row_idx]
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

        base = f"background-color: {bg.name()}; padding-left: 6px; font-size: 12px; font-weight: {font_weight};"
        base_r = f"background-color: {bg.name()}; padding-right: 6px; font-size: 12px; font-weight: {font_weight};"

        # 账号名
        widgets[0].setText(account_name)
        widgets[0].setStyleSheet(f"color: {TEXT.name()}; {base}")

        # 模型
        widgets[1].setText(provider["model"])
        widgets[1].setStyleSheet(f"color: {TEXT_DIM.name()}; {base}")

        if kind == "error":
            widgets[2].setText(res["error"])
            widgets[2].setStyleSheet(f"color: {RED.name()}; {base_r}")
            widgets[3].setText("")
            widgets[3].setStyleSheet(f"background-color: {bg.name()};")
        elif kind == "deepseek":
            try:
                bal = float(res.get("balance", "0"))
                color = ORANGE if bal < LOW_BALANCE_CNY else GREEN
            except ValueError:
                bal = 0.0
                color = TEXT
            widgets[2].setText(f"余额 ¥{res.get('balance', '--')}")
            widgets[2].setStyleSheet(f"color: {color.name()}; {base_r}")
        else:
            h5 = res.get("h5_remaining")
            d7 = res.get("d7_remaining")
            widgets[2].setText(self._fmt_pct(h5, res.get("h5_reset")))
            widgets[2].setStyleSheet(f"color: {self._pct_color(h5).name()}; {base_r}")
            widgets[3].setText(self._fmt_pct(d7, res.get("d7_reset"), compact=True))
            widgets[3].setStyleSheet(f"color: {self._pct_color(d7).name()}; {base_r}")

    def _render_error(self, message):
        self._clear_rows()
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
        self._morph = 0.0
        self._fade = 1.0          # 圆球元素（数字/底环）可见度
        self._arc_t = 1.0         # 彩环弧长系数（1=当前进度，0=缩没）
        self._table_fade = 0.0    # 表格文字可见度
        self._bg_opacity = 1.0    # 背景透明度（变形 dip 由 _set_morph 计算）
        self._radius = ORB_SIZE // 2
        self._table_w = ORB_SIZE
        self._table_h = ORB_SIZE

        # 圆球绘制状态（由 paintEvent 统一绘制）
        self._orb_pct = None
        self._orb_color = TEXT_DIM
        self._orb_text = "--"
        self._orb_font = QFont("Microsoft YaHei UI", 14, QFont.Bold)
        self._bg_brush = QBrush(BG)
        self._track_pen = QPen(ORB_TRACK, ORB_STROKE)
        self._track_pen.setCapStyle(Qt.RoundCap)
        self._text_pen = QPen(TEXT)

        # 拖动/点击状态
        self._drag_pos = QPoint()
        self._press_global = QPoint()
        self._pressed = False

        # 表格（初始隐藏）
        self.table = TableWidget(self)
        self.table.close_clicked.connect(self._collapse)
        self.table.refresh_clicked.connect(self.refresh)
        self.table.hide()

        # 表格淡入淡出
        self.table_fx = QGraphicsOpacityEffect(self.table)
        self.table.setGraphicsEffect(self.table_fx)
        self.table_fx.setOpacity(0.0)

        # V4 三阶段时序（展开）：
        #   阶段2（220ms）：彩环旋转回缩到 0（OutCubic，像被卷走）∥ 数字/底环线性淡出，
        #                   球背景全程保持 100% 不透明
        #   阶段3（280ms）：几何变形（OutCubic）∥ 表格文字线性渐显，
        #                   背景 dip 由 _set_morph 按 sin(π·morph) 计算（1.0→0.25→1.0，中段最虚）
        # 展开 = Sequential[orb_phase → morph_phase]，收起为完全对称的倒放。
        # 顺序组每次切换时重建（两个并行组不能同时挂在两个父组下），动画对象复用。
        self._arc_anim = QPropertyAnimation(self, b"arcProperty")
        self._arc_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._orb_fade_anim = QPropertyAnimation(self, b"fadeProperty")
        self._orb_fade_anim.setEasingCurve(QEasingCurve.Linear)
        self._morph_anim = QPropertyAnimation(self, b"morphProperty")
        self._morph_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._table_fade_anim = QPropertyAnimation(self, b"tableFadeProperty")
        self._table_fade_anim.setEasingCurve(QEasingCurve.Linear)
        self._seq = None

        # 点击窗口外部（应用失焦）时自动收起
        app = QApplication.instance()
        if app:
            app.applicationStateChanged.connect(self._on_app_state)

        # 自动刷新
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(REFRESH_INTERVAL_S * 1000)

        self._restore_state()
        self.resize(ORB_SIZE, ORB_SIZE)
        self.refresh()
        self._prewarm_table()

    def _prewarm_table(self):
        """启动时预热表格：构建所有行 widget 并创建 native 窗口，
        把 QLabel 创建、样式解析、字体加载、HWND 创建的开销全部消化在启动阶段，
        避免首次点击展开时卡顿。"""
        try:
            self._table_w, self._table_h = self._calc_table_size()
            self.table.resize(self._table_w, self._table_h)
            self.table.render(self.providers, self.results, self.error)
            # 强制创建 native window（show 一次再 hide）
            self.table.show()
            self.table.hide()
            self.table_fx.setOpacity(0.0)
            _ui_log("table prewarmed")
        except Exception as e:
            _ui_log(f"prewarm failed: {e}")

    # ---- 变形动画属性（几何） ----
    def _get_morph(self):
        return self._morph

    def _set_morph(self, v):
        self._morph = v
        # 窗口尺寸插值：圆球 → 表格，保持中心不动
        old_w, old_h = self.width(), self.height()
        old_cx = self.x() + old_w // 2
        old_cy = self.y() + old_h // 2
        w = int(ORB_SIZE + (self._table_w - ORB_SIZE) * v)
        h = int(ORB_SIZE + (self._table_h - ORB_SIZE) * v)
        # 单次几何变更（避免 resize+move 两次 DWM 合成导致抖动）
        self.setGeometry(old_cx - w // 2, old_cy - h // 2, w, h)
        # 表格随变形过半出现（内容由 fade 控制可见度）
        if v > 0.4 and not self.table.isVisible():
            self.table.show()
        elif v <= 0.4 and self.table.isVisible():
            self.table.hide()
        # 圆角半径：圆形 → 小圆角方形
        self._radius = int(ORB_SIZE / 2 + (8 - ORB_SIZE / 2) * v)
        # 背景 dip：随变形进度 1.0 → 0.25 → 1.0（中段最虚，变形结束即恢复扎实）
        self._bg_opacity = 1.0 - 0.75 * math.sin(math.pi * v)
        self.update()

    morphProperty = Property(float, _get_morph, _set_morph)

    # ---- 圆球元素可见度（数字/底环；彩环由 arcProperty 单独驱动） ----
    def _get_fade(self):
        return self._fade

    def _set_fade(self, v):
        self._fade = v
        self.update()

    fadeProperty = Property(float, _get_fade, _set_fade)

    # ---- 彩环弧长系数（1=当前进度，0=缩没；起点绕环旋转形成"旋转变少/变多"） ----
    def _get_arc_t(self):
        return self._arc_t

    def _set_arc_t(self, v):
        self._arc_t = v
        self.update()

    arcProperty = Property(float, _get_arc_t, _set_arc_t)

    # ---- 表格文字可见度 ----
    def _get_table_fade(self):
        return self._table_fade

    def _set_table_fade(self, v):
        self._table_fade = v
        self.table_fx.setOpacity(v)

    tableFadeProperty = Property(float, _get_table_fade, _set_table_fade)

    def paintEvent(self, event):
        """统一绘制：变形的球/方背景 + 圆球进度环与文字（随变形渐隐）。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()

        # 1. 变形背景：圆球模式是大圆角（正圆），表格模式是小圆角方形
        if self._bg_opacity > 0.01:
            painter.setOpacity(self._bg_opacity)
            path = QPainterPath()
            path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), self._radius, self._radius)
            painter.fillPath(path, self._bg_brush)

        # 2. 圆球元素（进度环 + 文字），可见度由 fade 控制
        if self._morph < 0.999 and self._fade > 0.01:
            painter.setOpacity(self._fade)
            cx, cy = w / 2, h / 2
            # 固定为圆球原始半径，不随变形放大
            r = ORB_SIZE / 2 - ORB_PAD
            ring_rect = QRectF(cx - r, cy - r, r * 2, r * 2)

            # 轨道环（深灰）
            painter.setPen(self._track_pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(ring_rect)

            # 彩色进度弧：终点固定在原位，起点随 _arc_t 绕环旋转推进，
            # 弧长同步缩短/增长 —— 旋转变少（展开）/ 旋转变多（收起）
            if self._orb_pct is not None and self._arc_t > 0.001:
                arc_pen = QPen(self._orb_color, ORB_STROKE)
                arc_pen.setCapStyle(Qt.RoundCap)
                painter.setPen(arc_pen)
                sweep = self._orb_pct * 3.6 * self._arc_t      # 当前弧长（度）
                start_deg = 90.0 - self._orb_pct * 3.6 + sweep  # 起点=终点角度+弧长
                span = -int(sweep * 16)
                if span != 0:
                    painter.drawArc(ring_rect, int(start_deg * 16), span)

            # 百分比文字
            painter.setPen(self._text_pen)
            painter.setFont(self._orb_font)
            painter.drawText(ring_rect, Qt.AlignCenter, self._orb_text)

        painter.end()

    # ---- 拖动 / 点击 ----
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self._press_global = event.globalPosition().toPoint()
            self._pressed = True

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._pressed:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._pressed:
            moved = (event.globalPosition().toPoint() - self._press_global).manhattanLength()
            if moved < 4 and self._morph < 0.5 and not self._anim_running():
                self._expand()
            self._pressed = False

    def _on_app_state(self, state):
        # 点击窗口外部（应用失焦）→ 自动收起回圆球
        if (state == Qt.ApplicationInactive
                and self._mode == "table"
                and self._morph >= 1.0
                and not self._anim_running()):
            self._collapse()

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
        if self._mode == "table" and self._morph >= 1.0:
            self._render_table()

    def _update_orb(self):
        provider = self.current_provider
        res = self.results.get(provider["id"], {}) if provider else {}
        pct, color, text = self._orb_value(provider, res)
        self._orb_pct = pct
        self._orb_color = color
        self._orb_text = text
        self.update()

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

    def _calc_table_size(self):
        row_count = len(self.providers) if self.providers else 1
        width = sum(COL_WIDTHS) + 20
        height = 28 + row_count * 28 + 40
        return width, height

    def _render_table(self):
        self.table.render(self.providers, self.results, self.error)
        self._table_w, self._table_h = self._calc_table_size()
        self.table.resize(self._table_w, self._table_h)
        if self._morph >= 1.0:
            self.resize(self._table_w, self._table_h)

    def _anim_running(self):
        return self._seq is not None and self._seq.state() == QAbstractAnimation.Running

    def _build_seq(self, collapse):
        """按方向重建顺序组（两个并行组不能同时挂在两个父组下，动画对象复用）。"""
        if self._seq is not None:
            self._seq.deleteLater()
        orb_phase = QParallelAnimationGroup(self)
        orb_phase.addAnimation(self._arc_anim)
        orb_phase.addAnimation(self._orb_fade_anim)
        morph_phase = QParallelAnimationGroup(self)
        morph_phase.addAnimation(self._morph_anim)
        morph_phase.addAnimation(self._table_fade_anim)
        seq = QSequentialAnimationGroup(self)
        seq.addAnimation(morph_phase if collapse else orb_phase)
        seq.addAnimation(orb_phase if collapse else morph_phase)
        seq.finished.connect(self._seq_finished)
        self._seq = seq
        return seq

    def _expand(self):
        if self._anim_running():
            return
        self._mode = "table"
        self._table_w, self._table_h = self._calc_table_size()
        self.table.resize(self._table_w, self._table_h)
        # 阶段2：彩环旋转回缩到 0（球背景保持 100% 不透明）∥ 数字/底环线性淡出
        self._arc_anim.setDuration(220)
        self._arc_anim.setStartValue(self._arc_t)
        self._arc_anim.setEndValue(0.0)
        self._orb_fade_anim.setDuration(220)
        self._orb_fade_anim.setStartValue(self._fade)
        self._orb_fade_anim.setEndValue(0.0)
        # 阶段3：变形 ∥ 表格渐显（背景 dip 在 _set_morph 内随变形计算，同起同止）
        self._morph_anim.setDuration(280)
        self._morph_anim.setStartValue(self._morph)
        self._morph_anim.setEndValue(1.0)
        self._table_fade_anim.setDuration(280)
        self._table_fade_anim.setStartValue(self._table_fade)
        self._table_fade_anim.setEndValue(1.0)
        self._build_seq(collapse=False).start()

    def _collapse(self):
        if self._anim_running():
            return
        self._mode = "orb"
        # 阶段1：表格文字渐隐 ∥ 方形收缩回圆球（背景 dip 同展开）
        self._morph_anim.setDuration(280)
        self._morph_anim.setStartValue(self._morph)
        self._morph_anim.setEndValue(0.0)
        self._table_fade_anim.setDuration(280)
        self._table_fade_anim.setStartValue(self._table_fade)
        self._table_fade_anim.setEndValue(0.0)
        # 阶段2：底环/数字渐显 ∥ 彩环从 0 旋转增长回当前进度
        self._arc_anim.setDuration(220)
        self._arc_anim.setStartValue(self._arc_t)
        self._arc_anim.setEndValue(1.0)
        self._orb_fade_anim.setDuration(220)
        self._orb_fade_anim.setStartValue(self._fade)
        self._orb_fade_anim.setEndValue(1.0)
        self._build_seq(collapse=True).start()

    def _seq_finished(self):
        # 动画序列结束：table 模式刷新内容，orb 模式触发一次重绘
        if self._mode == "table":
            self._render_table()
        else:
            self.update()
        self._save_state()

    def closeEvent(self, event):
        self._save_state()
        super().closeEvent(event)


def main():
    _reset_ui_log()
    _ui_log("=== main() start ===")
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(True)

        window = MainWindow()
        window.show()
        _ui_log(f"window shown: visible={window.isVisible()}, pos=({window.x()},{window.y()}), size={window.size()}")

        code = app.exec()
        _ui_log(f"=== app.exec() returned: {code} ===")
        sys.exit(code)
    except Exception:
        import traceback
        _ui_log("=== EXCEPTION ===\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
