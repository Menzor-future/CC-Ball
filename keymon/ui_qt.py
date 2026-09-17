# -*- coding: utf-8 -*-
"""PySide6 悬浮窗 UI：圆球仪表盘 + 展开表格。"""
import datetime as dt
import math
import os
import sys
import threading

from PySide6.QtCore import (
    QAbstractAnimation, QEasingCurve, QParallelAnimationGroup,
    QPropertyAnimation, Qt, QTimer, QVariantAnimation,
    Signal, QObject, QEvent, QRect, QRectF, QPoint, QPointF, QSize, Property,
    QSequentialAnimationGroup,
)
from PySide6.QtGui import (
    QColor, QCursor, QFont, QIcon, QPainter, QPainterPath, QPen, QBrush, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication, QFrame, QGridLayout, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QMainWindow, QMenu, QMessageBox, QSizePolicy, QSpacerItem,
    QSystemTrayIcon, QVBoxLayout, QWidget,
)

from . import autostart

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

# 变形几何调试：置 1 时记录每次 resize 的真实尺寸，并在启动后自动循环展开/收起
_DBG_MORPH = bool(os.environ.get("KEYMON_DBG_MORPH"))


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

# 悬停关闭小球
CLOSE_BTN_SIZE = 24          # 终点直径（完整按钮）
CLOSE_BTN_DOT_SIZE = 6       # 起点直径（圆球沿上的点）
CLOSE_BTN_POP_IN_MS = 450    # 飞出：球沿小点 → 悬浮卫星位
CLOSE_BTN_POP_OUT_MS = 350   # 收回：悬浮卫星位 → 球沿小点
CLOSE_BTN_HIDE_DELAY_MS = 200  # 移出后延迟隐藏，给"球→按钮"鼠标移动留缓冲，防闪烁


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


class CloseOrbButton(QWidget):
    """圆球右上角悬浮关闭小球：同设计语言（圆形深灰实底 + 细边 + 白色 ✕），hover 变红。
    位置压在圆球轮廓右上 45° 处——窗口角部透明，视觉上探出球沿。"""

    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # 独立小窗：可绘制在主窗口之外（子控件会被裁剪在父窗口内）
        # Tool + 无边框：不进任务栏、不抢 alt-tab；不抢焦点，点击不干扰主窗失焦逻辑
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        # 尺寸/位置由弹出动画驱动（球沿小点 → 悬浮卫星位）
        self.setCursor(Qt.PointingHandCursor)
        self._hovered = False
        self._bg = QColor(HEADER_BG)
        self._fg = QColor(TEXT)
        self._bg_hover = QColor(RED)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        d = float(self.width())
        # 圆形实底 + 细边（悬浮在透明角部，需要实底）
        p.setPen(QPen(GRID, 1))
        p.setBrush(QBrush(self._bg_hover if self._hovered else self._bg))
        p.drawEllipse(QRectF(0.5, 0.5, d - 1, d - 1))
        # ✕ 两根线
        pad = d * 0.32
        pen = QPen(self._fg, 1.8)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawLine(QPointF(pad, pad), QPointF(d - pad, d - pad))
        p.drawLine(QPointF(d - pad, pad), QPointF(pad, d - pad))
        p.end()

    def enterEvent(self, event):
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        # 自行处理点击：吞掉事件，避免冒泡到主窗口触发拖动/展开
        if event.button() == Qt.LeftButton:
            event.accept()
            self.clicked.emit()
        else:
            super().mousePressEvent(event)


class MainWindow(QMainWindow):
    """主窗口：根据模式显示圆球或表格。"""

    # 异步刷新完成信号：worker 线程 emit，主线程 queued 接收（providers, results, error）
    _refresh_done = Signal(object, object, object)

    def __init__(self):
        super().__init__()
        # Qt.Tool：不进任务栏、不出现在 Alt+Tab（v7，阿泽要求只留托盘入口）；
        # 置顶/拖动/展开动画行为不受影响（关闭小球同款先例）。
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # hover 期间也要收 mouseMoveEvent：合成 Enter 可能被吞（见 _close_suppress_pos），
        # 真实 hover 以"光标在窗内移动"兜底判定
        self.setMouseTracking(True)

        self.providers = []
        self.results = {}
        self.error = None
        self.current_provider = None
        self.cache = QuotaCache(ttl_s=60)
        self._refreshing = False   # 刷新重入守卫（worker 线程在飞时跳过新刷新）
        self._table_ready = False  # 首次数据到达后预热表格（替代启动时同步预热）
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

        # 悬停关闭小球（v6）：默认隐藏，orb 模式悬停时从球沿"弹出"到右上角
        self.close_btn = CloseOrbButton(self)
        # 弹出动画两端（轨迹=圆心 45° 放射直线）：起点=球面小点（距圆心 50px），
        # 终点=径向外飞 ~21px 后（距圆心 70px，父坐标 (88,-12)，与球肩缝隙 ~9px）
        # 注意：CloseOrbButton 是 Qt.Tool 独立顶层小窗，其 geometry 是【屏幕全局坐标】；
        # 以下常量均为父内坐标，读写一律经 _btn_set_parent_rect/_btn_parent_rect 换算（v6-9）。
        self._close_dot_rect = QRect(82, 12, CLOSE_BTN_DOT_SIZE, CLOSE_BTN_DOT_SIZE)
        self._close_full_rect = QRect(88, -12, CLOSE_BTN_SIZE, CLOSE_BTN_SIZE)
        self._btn_set_parent_rect(self._close_dot_rect)
        self.close_btn.clicked.connect(self._on_close_btn)
        self._close_btn_fx = QGraphicsOpacityEffect(self.close_btn)
        self.close_btn.setGraphicsEffect(self._close_btn_fx)
        self._close_btn_fx.setOpacity(0.0)
        self.close_btn.hide()
        self._close_pop_anim = QVariantAnimation(self)
        self._close_pop_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._close_pop_anim.valueChanged.connect(self._on_close_pop_frame)
        self._close_pop_anim.finished.connect(self._on_close_pop_done)
        self._close_pop_showing = False   # 当前动画方向
        self._pop_from_rect = self._close_dot_rect
        self._pop_to_rect = self._close_full_rect
        self._close_hide_timer = QTimer(self)
        self._close_hide_timer.setSingleShot(True)
        self._close_hide_timer.setInterval(CLOSE_BTN_HIDE_DELAY_MS)
        self._close_hide_timer.timeout.connect(self._start_close_pop_out)
        self.close_btn.installEventFilter(self)  # hover 桥接：进入按钮取消隐藏倒计时
        # v8：收回完成后 Qt 补发的"合成 Enter"防误判。收回结束时记录光标位置，
        # 光标未发生真实移动前的 Enter 一律视为合成事件（主窗改 Qt.Tool 后，
        # 该 Enter 会排在动画 finished 之后到达，"运行中"守卫失效）。
        self._close_suppress_pos = None

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

        self._refresh_done.connect(self._on_refresh_done)

        self._restore_state()
        self.resize(ORB_SIZE, ORB_SIZE)
        self.refresh()  # 异步：首次数据到达后在 _on_refresh_done 里预热表格

    def _prewarm_table(self):
        """首次数据到达后预热：构建所有行 widget 并强制创建 native 窗口，
        把 QLabel 创建、样式解析、字体加载、HWND 创建的开销消化在首次展开之前。"""
        self._table_w, self._table_h = self._calc_table_size()
        self.table.resize(self._table_w, self._table_h)
        self.table.render(self.providers, self.results, self.error)
        self.table.show()
        self.table.hide()
        self.table_fx.setOpacity(0.0)
        _ui_log("table prewarmed")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if _DBG_MORPH:
            s = event.size()
            _ui_log(f"[DBG] resize -> {s.width()}x{s.height()} morph={self._morph:.3f} running={self._anim_running()}")

    def moveEvent(self, event):
        super().moveEvent(event)
        # Qt.Tool 独立小窗不会自动跟随主窗，需手动吸附（拖动/变形时保持徽章位）。
        # 动画运行中跳过：帧处理器每帧实时换算全局坐标，天然跟随。
        btn = getattr(self, "close_btn", None)
        if btn is None:
            return
        if self._close_pop_anim.state() == QAbstractAnimation.Running:
            return
        target = self._close_full_rect if btn.isVisible() else self._close_dot_rect
        btn.move(self.mapToGlobal(target.topLeft()))

    # ---- 关闭小球坐标换算（v6-9：小窗 geometry 是屏幕全局坐标，常量是父内坐标） ----
    def _btn_parent_rect(self):
        """关闭小球当前几何换算回父内坐标。"""
        g = self.close_btn.geometry()
        return QRect(self.mapFromGlobal(g.topLeft()), g.size())

    def _btn_set_parent_rect(self, r):
        """以父内坐标设置关闭小球几何（换算为屏幕全局坐标写入）。"""
        self.close_btn.setGeometry(QRect(self.mapToGlobal(r.topLeft()), r.size()))

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
        if _DBG_MORPH:
            _ui_log(f"[DBG] morph req={w}x{h} v={v:.4f} table={self._table_w}x{self._table_h} actual={self.width()}x{self.height()}")
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
        if self._close_suppress_pos is not None:
            # 光标发生真实移动：解除合成 Enter 抑制，并按真实 hover 重新判定
            self._close_suppress_pos = None
            if (self._mode == "orb" and self._morph <= 0.01
                    and not self._anim_running()):
                self._start_close_pop_in()
        if event.buttons() & Qt.LeftButton and self._pressed:
            self.move(event.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self._pressed:
            moved = (event.globalPosition().toPoint() - self._press_global).manhattanLength()
            if moved < 4 and self._morph < 0.5 and not self._anim_running():
                self._expand()
            self._pressed = False

    # ---- 悬停关闭小球（v6） ----
    def enterEvent(self, event):
        super().enterEvent(event)
        if self._mode == "orb" and self._morph <= 0.01 and not self._anim_running():
            self._start_close_pop_in()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self._close_hide_timer.start()

    def eventFilter(self, obj, event):
        # hover 桥接：鼠标在"球 → 按钮"间移动时按钮不闪烁
        if obj is self.close_btn:
            if event.type() == QEvent.Enter:
                self._close_hide_timer.stop()
                self._close_suppress_pos = None  # 光标真实进入按钮 = 必有移动
                # 收回途中真实 hover 按钮（Enter 只在光标进入时产生，不会是合成假事件）：
                # 立即改向弹出，避免按钮从光标下"抽走"
                if (self._close_pop_anim.state() == QAbstractAnimation.Running
                        and not self._close_pop_showing):
                    self._start_close_pop(True)
            elif event.type() == QEvent.Leave:
                self._close_hide_timer.start()
        return super().eventFilter(obj, event)

    def _start_close_pop_in(self):
        self._close_hide_timer.stop()
        if self._close_pop_anim.state() == QAbstractAnimation.Running:
            return  # 弹出/收回动画进行中不重启：收回途中主窗 Enter 是按钮抽走时光标未动
        # 合成的假事件，真实返回由按钮 Enter（eventFilter）改向
        if (self._close_suppress_pos is not None
                and QCursor.pos() == self._close_suppress_pos):
            return  # v8：收回完成后补发的合成 Enter，光标未动 → 非真实 hover
        if (self.close_btn.isVisible()
                and self._close_btn_fx.opacity() >= 0.99
                and self._btn_parent_rect() == self._close_full_rect):
            return  # 已完整弹出
        self._close_suppress_pos = None
        self._start_close_pop(True)

    def _start_close_pop_out(self):
        if not self.close_btn.isVisible():
            return
        if (self._close_pop_anim.state() == QAbstractAnimation.Running
                and not self._close_pop_showing):
            return  # 收回进行中不重启（按钮抽走触发的 Leave 会重置倒计时，到点勿打断）
        self._start_close_pop(False)

    def _start_close_pop(self, showing):
        self._close_pop_showing = showing
        self._pop_from_rect = self._btn_parent_rect()   # 统一在父内坐标系插值
        self._pop_to_rect = self._close_full_rect if showing else self._close_dot_rect
        if showing:
            self.close_btn.show()
        self._close_pop_anim.stop()
        self._close_pop_anim.setDuration(CLOSE_BTN_POP_IN_MS if showing else CLOSE_BTN_POP_OUT_MS)
        self._close_pop_anim.setStartValue(0.0)
        self._close_pop_anim.setEndValue(1.0)
        self._close_pop_anim.start()

    def _on_close_pop_frame(self, v):
        # v：0→1（OutCubic 已施加）。收起时反向映射，形成"被吸回球沿"的手感。
        # 插值在父内坐标系进行，写入时换算为屏幕全局坐标（小窗 geometry 是全局的）。
        f = float(v) if self._close_pop_showing else 1.0 - float(v)
        fr, to = self._pop_from_rect, self._pop_to_rect
        x = round(fr.x() + (to.x() - fr.x()) * f)
        y = round(fr.y() + (to.y() - fr.y()) * f)
        w = round(fr.width() + (to.width() - fr.width()) * f)
        h = round(fr.height() + (to.height() - fr.height()) * f)
        self._btn_set_parent_rect(QRect(x, y, w, h))
        # 透明度快速 ramp：前一半进度即实心，收尾段淡出
        self._close_btn_fx.setOpacity(max(0.0, min(1.0, f * 2.0)))

    def _on_close_pop_done(self):
        if not self._close_pop_showing:
            self.close_btn.hide()
            self._btn_set_parent_rect(self._close_dot_rect)
            self._close_btn_fx.setOpacity(0.0)
            # 记录 dismissal 时光标位置：此后光标未动的 Enter 视为 Qt 补发的合成事件
            self._close_suppress_pos = QCursor.pos()

    def _dismiss_close_btn(self):
        """模式切换（展开/收起）时立即撤掉小球（无动画）。"""
        self._close_hide_timer.stop()
        self._close_pop_anim.stop()
        self.close_btn.hide()
        self._btn_set_parent_rect(self._close_dot_rect)
        self._close_btn_fx.setOpacity(0.0)
        self._close_suppress_pos = None

    def _on_close_btn(self):
        if self._anim_running() or self._morph > 0.01:
            return
        self._confirm_quit()

    def _build_quit_box(self):
        """退出确认弹窗（深色定制、置顶跟随主窗口、默认聚焦取消）。"""
        box = QMessageBox(self)
        box.setWindowTitle("Key 用量面板")
        box.setText("确认关闭 Key 用量面板吗？")
        box.setIcon(QMessageBox.NoIcon)
        btn_quit = box.addButton("确认关闭", QMessageBox.AcceptRole)
        btn_cancel = box.addButton("取消", QMessageBox.RejectRole)
        box.setDefaultButton(btn_cancel)
        box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
        box.setStyleSheet(
            f"QMessageBox {{ background-color: {BG.name()}; }}"
            f" QMessageBox QLabel {{ color: {TEXT.name()}; font-size: 13px; }}"
            f" QPushButton {{ background-color: {HEADER_BG.name()}; color: {TEXT.name()};"
            f"  border: 1px solid {GRID.name()}; border-radius: 6px; padding: 6px 18px; }}"
            f" QPushButton:hover {{ background-color: {GRID.name()}; }}"
            f" QPushButton:default {{ border: 1px solid {ACCENT.name()}; }}"
        )
        return box, btn_quit

    def _confirm_quit(self):
        box, btn_quit = self._build_quit_box()
        box.exec()
        if box.clickedButton() is btn_quit:
            self._save_state()
            QApplication.instance().quit()

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
        """异步刷新：DB 读取 + 网络查询全部在 worker 线程完成，结果经信号回主线程。
        主线程永不阻塞——否则网络变慢时会卡住事件循环，把正在进行的变形动画冻住
        （阿泽上报的"变形期间宽度偶尔被影响"即此因）。"""
        if self._refreshing:
            return
        self._refreshing = True

        def _work():
            try:
                data = read_providers()
                providers = data.get("providers", [])
                error = data.get("error")
                results = fetch_all(providers, cache=self.cache) if not error and providers else {}
                self._refresh_done.emit(providers, results, error)
            except Exception as e:
                _ui_log(f"refresh worker failed: {e}")
                self._refresh_done.emit([], {}, f"刷新失败: {e}")

        threading.Thread(target=_work, daemon=True).start()

    def _on_refresh_done(self, providers, results, error):
        self._refreshing = False
        self.providers = providers
        self.results = results
        self.error = error
        self.current_provider = next((p for p in providers if p["is_current"]), providers[0] if providers else None)

        self._update_orb()
        try:
            if not self._table_ready:
                self._table_ready = True
                self._prewarm_table()
            elif self._mode == "table" and self._morph >= 1.0:
                self._render_table()
        except Exception as e:
            _ui_log(f"render after refresh failed: {e}")

    def _update_orb(self):
        provider = self.current_provider
        res = self.results.get(provider["id"], {}) if provider else {}
        pct, color, text = self._orb_value(provider, res)
        self._orb_pct = pct
        self._orb_color = color
        self._orb_text = text
        self.update()
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.update_orb(pct, color)

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
        if self._anim_running() or self._morph >= 1.0:
            return
        self._dismiss_close_btn()
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
        if self._anim_running() or self._morph <= 0.0:
            return
        self._dismiss_close_btn()
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


class TrayController(QObject):
    """系统托盘（v7）：右键菜单（显示/隐藏面板、开机自启勾选、退出），左键切换可见性。
    图标与圆球同设计语言（深灰底 + 轨道环 + 彩弧），并跟随圆球当前用量变色。"""

    def __init__(self, window):
        super().__init__()
        self._window = window

        self._tray = QSystemTrayIcon(self)
        self._tray.setToolTip("Key 用量面板")
        self._tray.setIcon(self._make_icon(None, TEXT_DIM))

        self._menu = QMenu()
        self._menu.setStyleSheet(
            f"QMenu {{ background-color: {BG.name()}; color: {TEXT.name()};"
            f" border: 1px solid {GRID.name()}; }}"
            f" QMenu::item {{ padding: 6px 24px 6px 20px; }}"
            f" QMenu::item:selected {{ background-color: {GRID.name()}; }}"
            f" QMenu::item:checked {{ color: {ACCENT.name()}; }}"
            f" QMenu::separator {{ height: 1px; background-color: {GRID.name()}; margin: 4px 8px; }}"
        )
        self._toggle_action = self._menu.addAction("隐藏面板")
        self._toggle_action.triggered.connect(self._toggle_window)
        self._autostart_action = self._menu.addAction("开机自启动")
        self._autostart_action.setCheckable(True)
        try:
            self._autostart_action.setChecked(autostart.is_enabled())
        except Exception as e:
            _ui_log(f"tray: read autostart state failed: {e}")
        self._autostart_action.toggled.connect(self._on_autostart_toggled)
        self._menu.addSeparator()
        self._quit_action = self._menu.addAction("退出")
        self._quit_action.triggered.connect(self._window._confirm_quit)

        self._menu.aboutToShow.connect(self._sync_toggle_text)
        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)
        self._tray.show()

    def update_orb(self, pct, color):
        """圆球数据刷新时同步托盘图标（彩弧 = 当前 5h 已用量）。"""
        self._tray.setIcon(self._make_icon(pct, color))

    @staticmethod
    def _make_icon(pct, color):
        pm = QPixmap(32, 32)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(BG)))
        p.drawEllipse(2, 2, 28, 28)
        ring = QRectF(7, 7, 18, 18)
        track_pen = QPen(ORB_TRACK, 3)
        track_pen.setCapStyle(Qt.RoundCap)
        p.setPen(track_pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(ring)
        if pct is not None:
            arc_pen = QPen(color, 3)
            arc_pen.setCapStyle(Qt.RoundCap)
            p.setPen(arc_pen)
            p.drawArc(ring, 90 * 16, -int(pct * 3.6 * 16))
        p.end()
        return QIcon(pm)

    def _sync_toggle_text(self):
        self._toggle_action.setText("隐藏面板" if self._window.isVisible() else "显示面板")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:  # 左键单击
            self._toggle_window()

    def _toggle_window(self):
        w = self._window
        if w.isVisible():
            w.hide()
        else:
            w.show()
            w.raise_()

    def _on_autostart_toggled(self, checked):
        try:
            if checked:
                autostart.enable()
            else:
                autostart.disable()
            _ui_log(f"tray: autostart -> {'on' if checked else 'off'}")
        except Exception as e:
            _ui_log(f"tray: autostart toggle failed: {e}")
            # 写注册表失败：回退勾选，与注册表实际状态保持一致
            try:
                self._autostart_action.setChecked(autostart.is_enabled())
            except Exception:
                pass


def main():
    _reset_ui_log()
    _ui_log("=== main() start ===")
    try:
        app = QApplication(sys.argv)
        # 有托盘时"最后窗口关闭不退出"（任务栏已无入口，退出只能走托盘菜单）；
        # 托盘不可用降级为旧行为：关窗即退出。
        tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        app.setQuitOnLastWindowClosed(not tray_available)

        window = MainWindow()
        window.show()
        _ui_log(f"window shown: visible={window.isVisible()}, pos=({window.x()},{window.y()}), size={window.size()}")

        if tray_available:
            window._tray = TrayController(window)
        else:
            _ui_log("WARN: system tray not available, tray disabled")

        if _DBG_MORPH:
            _ui_log(f"[DBG] devicePixelRatioF={window.devicePixelRatioF()} screenDPI={window.screen().logicalDotsPerInch()}")
            # 自动循环展开/收起；每周期中途注入 refresh()（模拟60s自动刷新撞上变形）
            # 和微小 move()（模拟变形期间鼠标拖动），配合 resizeEvent 日志定位几何抖动
            def _cycle(n=0):
                if n >= 30:
                    _ui_log("[DBG] self-test done")
                    app.quit()
                    return
                (window._collapse if window._mode == "table" else window._expand)()
                phase = window._morph_anim.duration()
                if n % 2 == 0:
                    QTimer.singleShot(phase // 2, window.refresh)          # 变形中段刷新
                if n % 3 == 0:
                    QTimer.singleShot(phase // 3, lambda: window.move(window.x() + 3, window.y()))  # 微拖动
                QTimer.singleShot(900, lambda: _cycle(n + 1))

            QTimer.singleShot(2500, lambda: _cycle(0))

        code = app.exec()
        _ui_log(f"=== app.exec() returned: {code} ===")
        sys.exit(code)
    except Exception:
        import traceback
        _ui_log("=== EXCEPTION ===\n" + traceback.format_exc())
        raise


if __name__ == "__main__":
    main()
