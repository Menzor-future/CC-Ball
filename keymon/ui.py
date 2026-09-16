# -*- coding: utf-8 -*-
"""悬浮窗 UI：默认圆球仪表盘，点击展开完整表格。"""
import ctypes
import datetime as dt
import os
import threading
import tkinter as tk
from tkinter import font as tkfont

from .config import (
    LOW_BALANCE_CNY,
    REFRESH_INTERVAL_S,
    USER_CONFIG_PATH,
    WINDOW_ALPHA,
    load_user_config,
    save_user_config,
)
from .ccdb import read_providers
from .quota import QuotaCache, fetch_all

# 诊断日志路径（仅用于排查 UI 问题）
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


# 配色（深色玻璃风；文字保持 100% 不透明）
BG = "#1a1a20"
BG_CURRENT = "#2a2530"
TEXT = "#e6e6ea"
TEXT_DIM = "#8b8b95"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
ORANGE = "#d29922"
RED = "#f85149"
HEADER_BG = "#25252c"
GRID = "#35353d"
TRANSPARENT = "#010203"

COLS = ["账号名", "模型", "5h", "7day"]
COL_WIDTHS = [110, 120, 105, 105]

ORB_SIZE = 120
ORB_PAD = 8
ORB_STROKE = 8


class UsageWidget(tk.Tk):
    def __init__(self):
        super().__init__()
        self.configure(bg=TRANSPARENT)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.withdraw()  # 首次渲染完成前隐藏，避免默认尺寸闪现

        # 字体
        self.font_header = tkfont.Font(family="Microsoft YaHei UI", size=9, weight="bold")
        self.font_body = tkfont.Font(family="Microsoft YaHei UI", size=9)
        self.font_body_bold = tkfont.Font(family="Microsoft YaHei UI", size=9, weight="bold")
        self.font_small = tkfont.Font(family="Microsoft YaHei UI", size=8)
        self.font_orb = tkfont.Font(family="Microsoft YaHei UI", size=14, weight="bold")

        # 数据与状态
        self.providers = []
        self.results = {}
        self.error = None
        self.current_provider = None
        self.cache = QuotaCache(ttl_s=60)
        self._refresh_in_progress = False
        self._auto_refresh_id = None
        self._first_show_pending = True
        self._mode = "orb"  # "orb" | "table"

        # 拖动
        self._drag_x = self._drag_y = 0
        self.bind("<ButtonPress-1>", self._start_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._stop_drag)

        self._build_orb_view()
        self._build_table_view()
        self._build_anim_canvas()

        _reset_ui_log()
        _ui_log("UsageWidget init")

        self._restore_state()
        self.refresh()

    def _verify_center_pixel(self):
        """读取窗口多个位置像素颜色，定位黑块来源。"""
        try:
            hwnd = self.winfo_id()
            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32

            user32.GetDC.restype = ctypes.c_void_p
            user32.GetDC.argtypes = [ctypes.c_void_p]
            hdc = user32.GetDC(hwnd)

            gdi32.GetPixel.restype = ctypes.c_ulong
            gdi32.GetPixel.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int]

            # 读取多个位置：中心、左上、右上、左下、右下
            points = [
                ("center", ORB_SIZE // 2, ORB_SIZE // 2),
                ("topleft", 5, 5),
                ("topright", ORB_SIZE - 5, 5),
                ("bottomleft", 5, ORB_SIZE - 5),
                ("bottomright", ORB_SIZE - 5, ORB_SIZE - 5),
                ("midright", ORB_SIZE - 5, ORB_SIZE // 2),
                ("midbottom", ORB_SIZE // 2, ORB_SIZE - 5),
            ]
            for name, px, py in points:
                pixel = gdi32.GetPixel(hdc, px, py)
                r = pixel & 0xFF
                g = (pixel >> 8) & 0xFF
                b = (pixel >> 16) & 0xFF
                _ui_log(f"pixel[{name}]: raw=0x{pixel:06x} RGB=({r},{g},{b})")

            user32.ReleaseDC.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
            user32.ReleaseDC(hwnd, hdc)

            # 记录窗口几何
            geo = self.geometry()
            _ui_log(f"window geometry: {geo}")
        except Exception as exc:
            _ui_log(f"verify pixel EXCEPTION: {type(exc).__name__}: {exc}")

    # ---- 视图构建 ----
    def _build_orb_view(self):
        self.orb_frame = tk.Frame(self, bg=TRANSPARENT, width=ORB_SIZE, height=ORB_SIZE)
        self.orb_frame.grid(row=0, column=0, sticky="nsew")
        self.orb_frame.grid_propagate(False)

        self.orb_canvas = tk.Canvas(
            self.orb_frame, width=ORB_SIZE, height=ORB_SIZE,
            bg=TRANSPARENT, highlightthickness=0,
        )
        self.orb_canvas.pack(fill="both", expand=True)

        r = ORB_SIZE // 2 - ORB_PAD
        cx = ORB_SIZE // 2
        cy = ORB_SIZE // 2
        x0, y0 = cx - r, cy - r
        x1, y1 = cx + r, cy + r

        self.orb_bg_oval = self.orb_canvas.create_oval(
            x0, y0, x1, y1, outline=GRID, width=ORB_STROKE,
        )
        self.orb_arc = self.orb_canvas.create_arc(
            x0, y0, x1, y1, start=90, extent=0,
            outline=GREEN, width=ORB_STROKE, style="arc",
        )
        self.orb_text = self.orb_canvas.create_text(
            cx, cy, text="--", fill=TEXT, font=self.font_orb,
        )

        self.orb_text_value = "--"

    def _build_anim_canvas(self):
        self.anim_canvas = tk.Canvas(
            self, bg=TRANSPARENT, highlightthickness=0,
        )
        self.anim_canvas.grid(row=0, column=0, sticky="nsew")
        self.anim_canvas.grid_remove()

    def _build_table_view(self):
        self.table_frame = tk.Frame(self, bg=TRANSPARENT)
        self.table_frame.grid(row=0, column=0, sticky="nsew")
        self.table_frame.grid_remove()  # 默认隐藏

        self.table = tk.Frame(self.table_frame, bg=GRID, padx=1, pady=1)
        self.table.grid(row=0, column=0, sticky="nsew", padx=8, pady=(0, 0))

        # 表头
        for col, (label, width) in enumerate(zip(COLS, COL_WIDTHS)):
            cell = tk.Frame(self.table, bg=HEADER_BG, width=width, height=26)
            cell.grid(row=0, column=col, sticky="nsew", padx=1, pady=1)
            cell.grid_propagate(False)
            tk.Label(
                cell, text=label, fg=TEXT_DIM, bg=HEADER_BG,
                font=self.font_small, anchor="w",
            ).pack(side="left", padx=6)

        self._rows = []

        self.footer = tk.Frame(self.table_frame, bg=BG, padx=8, pady=4)
        self.footer.grid(row=1, column=0, sticky="ew")

        self.refresh_btn = tk.Label(
            self.footer, text="⟳", fg=ACCENT, bg=BG,
            font=self.font_body, cursor="hand2",
        )
        self.refresh_btn.pack(side="left")
        self.refresh_btn.bind("<Button-1>", lambda _e: self.refresh())

        self.updated_label = tk.Label(
            self.footer, text="", fg=TEXT_DIM, bg=BG,
            font=self.font_small, anchor="e",
        )
        self.updated_label.pack(side="left", fill="x", expand=True, padx=(8, 0))

        self.close_btn = tk.Label(
            self.footer, text="✕", fg=TEXT_DIM, bg=BG,
            font=self.font_body, cursor="hand2",
        )
        self.close_btn.pack(side="right")
        self.close_btn.bind("<Button-1>", lambda _e: self._show_orb())

    # ---- 背景 ----
    def _apply_glass_background(self):
        """Windows 11 用 DWM 设置 Acrylic/Mica；失败则退回 tkinter alpha。"""
        hwnd = self.winfo_id()
        _ui_log(f"_apply_glass_background: hwnd={hwnd}")
        ok = _set_window_transparent(hwnd)
        _ui_log(f"_apply_glass_background: transparent={ok}")
        # 禁用 DWM Acrylic/Mica，避免覆盖 color key
        # if not _set_window_acrylic_mica(hwnd):
        #     self.attributes("-alpha", WINDOW_ALPHA)
        # 验证窗口中心像素颜色
        self.after(2000, self._verify_center_pixel)

    # ---- 拖动 ----
    def _start_drag(self, event):
        self._drag_x, self._drag_y = event.x, event.y

    def _on_drag(self, event):
        x = self.winfo_x() + event.x - self._drag_x
        y = self.winfo_y() + event.y - self._drag_y
        self.geometry(f"+{x}+{y}")

    def _stop_drag(self, event=None):
        moved = 0
        if event:
            moved = abs(event.x - self._drag_x) + abs(event.y - self._drag_y)
        if moved < 4 and self._mode == "orb":
            self._show_table()
        self._save_state()

    # ---- 模式切换 ----
    def _show_orb(self):
        if self._mode == "orb":
            return
        self._mode = "orb"
        self.configure(bg=TRANSPARENT)
        self.table_frame.grid_remove()
        self.orb_frame.grid()
        self.geometry(self._centered_geometry(ORB_SIZE, ORB_SIZE))
        self._save_state()
        _ui_log("mode -> orb")

    def _show_table(self):
        if self._mode == "table":
            return
        self._start_expand_animation()

    def _start_expand_animation(self):
        _ui_log("start expand animation")
        # 准备表格（文字先隐藏），但不调整窗口尺寸
        self._render_table(self.providers, self.results, self.error, finalize_geometry=False)
        self._set_table_text_color(BG)
        self.configure(bg=BG)
        self.table_frame.grid()
        self.orb_frame.grid_remove()

        # 强制回到 orb 尺寸作为动画起点
        self.geometry(self._centered_geometry(ORB_SIZE, ORB_SIZE))

        start_size = (ORB_SIZE, ORB_SIZE)
        end_w, end_h = self._compute_table_geometry(len(self.providers) if self.providers else 1)
        end_size = (end_w, end_h)

        self.anim_canvas.config(width=ORB_SIZE, height=ORB_SIZE, bg=TRANSPARENT)
        self.anim_canvas.grid()

        self._animate_expand(0, 12, start_size, end_size)

    def _animate_expand(self, step, total, start_size, end_size):
        progress = step / total
        cur_w = int(start_size[0] + (end_size[0] - start_size[0]) * progress)
        cur_h = int(start_size[1] + (end_size[1] - start_size[1]) * progress)
        self.geometry(self._centered_geometry(cur_w, cur_h))
        self.anim_canvas.config(width=cur_w, height=cur_h, bg=TRANSPARENT)

        cx, cy = cur_w // 2, cur_h // 2
        self.anim_canvas.delete("all")

        # 扩张的透黑圆形 -> 覆盖整个窗口后看起来是方形
        max_r = int((cur_w ** 2 + cur_h ** 2) ** 0.5 / 2) + 10
        base_r = ORB_SIZE // 2 - ORB_PAD
        r = int(base_r + (max_r - base_r) * progress)
        fill_color = _lerp_color(BG, "#050505", progress)
        self.anim_canvas.create_oval(cx - r, cy - r, cx + r, cy + r, fill=fill_color, outline="")

        # 文字渐隐
        text_color = _lerp_color(TEXT, fill_color, progress)
        self.anim_canvas.create_text(cx, cy, text=self.orb_text_value, fill=text_color, font=self.font_orb)

        # 列表文字渐显（后 40%）
        if progress > 0.5:
            table_progress = (progress - 0.5) / 0.5
            self._set_table_text_color(_lerp_color(BG, TEXT, table_progress))

        if step < total:
            self.after(16, lambda: self._animate_expand(step + 1, total, start_size, end_size))
        else:
            self.anim_canvas.grid_remove()
            self._set_table_text_color(TEXT)
            self._mode = "table"
            self._save_state()
            _ui_log("expand animation done")

    def _set_table_text_color(self, color):
        """批量设置表格及 footer 中所有 Label 的前景文字颜色。"""
        for widget in self.table_frame.winfo_children():
            for child in widget.winfo_children():
                if isinstance(child, tk.Label):
                    try:
                        child.config(fg=color)
                    except tk.TclError:
                        pass
                for grandchild in child.winfo_children():
                    if isinstance(grandchild, tk.Label):
                        try:
                            grandchild.config(fg=color)
                        except tk.TclError:
                            pass
        for widget in self.footer.winfo_children():
            if isinstance(widget, tk.Label):
                try:
                    widget.config(fg=color)
                except tk.TclError:
                    pass

    # ---- 几何位置 ----
    def _centered_geometry(self, width, height):
        """以当前窗口中心为锚点，返回新的几何字符串。"""
        geo = self.geometry()
        try:
            size, pos = geo.split("+", 1)
            cur_w, cur_h = map(int, size.split("x"))
            x, y = map(int, pos.split("+", 1))
            cx = x + cur_w // 2
            cy = y + cur_h // 2
            nx = max(0, cx - width // 2)
            ny = max(0, cy - height // 2)
            return f"{width}x{height}+{nx}+{ny}"
        except Exception:
            return f"{width}x{height}+80+80"

    def _restore_state(self):
        cfg = load_user_config()
        saved_mode = cfg.get("mode", "orb")
        geo = cfg.get("geometry")
        x = y = 80
        if geo:
            try:
                # 只读取位置，尺寸根据当前 mode 重新计算
                parts = geo.split("+", 1)
                if len(parts) == 2:
                    x, y = map(int, parts[1].split("+", 1))
            except Exception:
                pass

        # 启动时强制使用 orb 模式，避免上次 table 模式的尺寸导致黑块
        self._mode = "orb"
        width, height = ORB_SIZE, ORB_SIZE
        self.geometry(f"{width}x{height}+{x}+{y}")
        _ui_log(f"_restore_state: saved_mode={saved_mode}, force orb, pos={x},{y}")

    def _set_default_geometry(self):
        if self._mode == "table":
            width, height = self._compute_table_geometry(len(self.providers) if self.providers else 1)
        else:
            width, height = ORB_SIZE, ORB_SIZE
        self.geometry(f"{width}x{height}+80+80")

    def _compute_table_geometry(self, data_rows):
        """根据数据行数精确计算表格窗口宽高。"""
        cell_grid_pad_x = 1  # 单侧
        table_frame_pad_x = 8  # 单侧
        width = sum(COL_WIDTHS) + len(COL_WIDTHS) * cell_grid_pad_x * 2 + table_frame_pad_x * 2

        table_header_h = 28
        row_h = 28
        footer_h = 24
        height = table_header_h + data_rows * row_h + footer_h
        return width, height

    def _save_state(self):
        cfg = load_user_config()
        cfg["geometry"] = self.geometry()
        cfg["mode"] = self._mode
        save_user_config(cfg)

    # ---- 刷新 ----
    def refresh(self, _event=None):
        if self._refresh_in_progress:
            return
        self._refresh_in_progress = True
        self.refresh_btn.config(text="···", fg=TEXT_DIM)

        def job():
            try:
                data = read_providers()
                providers = data.get("providers", [])
                error = data.get("error")
                results = fetch_all(providers, cache=self.cache) if not error and providers else {}
                self.after(0, self._on_data_ready, providers, results, error)
            finally:
                self.after(0, lambda: self.refresh_btn.config(text="⟳", fg=ACCENT))
                self._refresh_in_progress = False
                self._schedule_auto_refresh()

        threading.Thread(target=job, daemon=True).start()

    def _schedule_auto_refresh(self):
        if self._auto_refresh_id is not None:
            self.after_cancel(self._auto_refresh_id)
        self._auto_refresh_id = self.after(REFRESH_INTERVAL_S * 1000, self.refresh)

    def _on_data_ready(self, providers, results, error):
        self.providers = providers
        self.results = results
        self.error = error
        self.current_provider = next((p for p in providers if p["is_current"]), providers[0] if providers else None)
        self._update_orb()
        if self._mode == "table":
            self._render_table(providers, results, error)
        if self._first_show_pending:
            self._first_show_pending = False
            _ui_log("deiconify first show")
            # 首次显示前确保几何正确
            if self._mode == "orb":
                self.geometry(self._centered_geometry(ORB_SIZE, ORB_SIZE))
            self.deiconify()
            self._apply_glass_background()

    # ---- 圆球更新 ----
    def _update_orb(self):
        provider = self.current_provider
        res = self.results.get(provider["id"], {}) if provider else {}
        pct, color, text = self._orb_value(provider, res)
        self.orb_text_value = text

        extent = -360 * (pct / 100) if pct is not None else 0
        self.orb_canvas.itemconfig(self.orb_arc, extent=extent, outline=color)
        self.orb_canvas.itemconfig(self.orb_text, text=text, fill=color)

    def _orb_value(self, provider, res):
        """返回 (百分比数字, 弧线颜色, 显示文字)。"""
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
        # DeepSeek / Claude 等没有 5h 百分比的显示 N/A
        return None, TEXT_DIM, "N/A"

    @staticmethod
    def _used_color(used):
        if used >= 0.8:
            return RED
        if used >= 0.5:
            return ORANGE
        return GREEN

    # ---- 表格渲染 ----
    def _render_table(self, providers, results, error, finalize_geometry=True):
        try:
            _ui_log(f"_render_table: providers={len(providers)} error={error}")

            # 清旧行
            for row_cells in self._rows:
                for cell in row_cells:
                    if cell is not None:
                        cell.destroy()
            self._rows.clear()

            if error:
                self._render_error(error)
                if finalize_geometry:
                    self._finalize_table_geometry(data_rows=2)
                return
            if not providers:
                self._render_error("未找到 provider 配置")
                if finalize_geometry:
                    self._finalize_table_geometry(data_rows=2)
                return

            for row_idx, provider in enumerate(providers, start=1):
                self._render_provider_row(row_idx, provider, results.get(provider["id"], {}))

            if finalize_geometry:
                self._finalize_table_geometry(data_rows=len(providers))
            self.updated_label.config(text=f"更新于 {dt.datetime.now().strftime('%H:%M:%S')}")
        except Exception as exc:
            _ui_log(f"_render_table EXCEPTION: {type(exc).__name__}: {exc}")
            raise

    def _finalize_table_geometry(self, data_rows=0):
        width, height = self._compute_table_geometry(data_rows)
        self.geometry(self._centered_geometry(width, height))
        self._save_state()

    def _render_provider_row(self, row_idx, provider, res):
        is_current = provider["is_current"]
        bg = BG_CURRENT if is_current else BG
        font = self.font_body_bold if is_current else self.font_body
        cells = []

        ptype = provider["provider_type"]
        account_name = provider["name"]
        if ptype == "kimi":
            account_name = res.get("account_name") or provider["name"]
        elif ptype == "deepseek":
            account_name = "DeepSeek"
        elif ptype == "anthropic":
            account_name = "Claude"

        cells.append(self._cell(row_idx, 0, account_name, bg, font=font, anchor="w"))
        cells.append(self._cell(row_idx, 1, provider["model"], bg, font=font, anchor="w", fg=TEXT_DIM))

        if "error" in res:
            cells.append(self._cell(row_idx, 2, res["error"], bg, font=font, fg=RED, anchor="e"))
            cells.append(self._cell(row_idx, 3, "", bg, font=font))
        elif ptype == "deepseek":
            try:
                bal = float(res.get("balance", "0"))
                color = ORANGE if bal < LOW_BALANCE_CNY else GREEN
            except ValueError:
                bal = 0.0
                color = TEXT
            text = f"余额 ¥{res.get('balance', '--')}"
            cell = tk.Frame(self.table, bg=bg, width=COL_WIDTHS[2] + COL_WIDTHS[3] + 2, height=26)
            cell.grid(row=row_idx, column=2, columnspan=2, sticky="nsew", padx=1, pady=1)
            cell.grid_propagate(False)
            tk.Label(
                cell, text=text, fg=color, bg=bg,
                font=font, anchor="e",
            ).pack(side="right", padx=6)
            cells.append(cell)
        else:
            h5 = res.get("h5_remaining")
            d7 = res.get("d7_remaining")
            cells.append(self._cell(
                row_idx, 2,
                self._fmt_pct(h5, res.get("h5_reset")), bg, font=font,
                fg=self._pct_color(h5), anchor="e",
            ))
            cells.append(self._cell(
                row_idx, 3,
                self._fmt_pct(d7, res.get("d7_reset"), compact=True), bg, font=font,
                fg=self._pct_color(d7), anchor="e",
            ))

        self._rows.append(cells)

    def _cell(self, row, col, text, bg, fg=TEXT, font=None, anchor="w"):
        cell = tk.Frame(self.table, bg=bg, width=COL_WIDTHS[col], height=26)
        cell.grid(row=row, column=col, sticky="nsew", padx=1, pady=1)
        cell.grid_propagate(False)
        tk.Label(
            cell, text=text, fg=fg, bg=bg,
            font=font or self.font_body, anchor=anchor,
        ).pack(side="left" if anchor == "w" else "right", padx=6)
        return cell

    def _render_error(self, message):
        cell = tk.Frame(self.table, bg=BG, width=sum(COL_WIDTHS) + 6, height=60)
        cell.grid(row=1, column=0, columnspan=4, sticky="nsew", padx=1, pady=1)
        tk.Label(
            cell, text=message, fg=RED, bg=BG,
            font=self.font_body, wraplength=320,
        ).pack(expand=True)
        self._rows.append([cell])

    @staticmethod
    def _fmt_pct(value, reset_time=None, compact=False):
        pct = UsageWidget._fmt_pct_raw(value)
        if value is None or not reset_time:
            return pct
        return f"{pct} ({UsageWidget._fmt_countdown(reset_time, compact=compact)})"

    @staticmethod
    def _fmt_pct_raw(value):
        if value is None:
            return "N/A"
        return f"{max(0.0, min(1.0, value)) * 100:.0f}%"

    @staticmethod
    def _fmt_countdown(reset_time, compact=False):
        """把 ISO reset_time 格式化为剩余时间。compact=True 时只显示最大单位，适合 7day 列。"""
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


def _lerp_color(c1, c2, t):
    """在两个 #RRGGBB 颜色之间线性插值，t in [0, 1]。"""
    def parse(c):
        c = c.lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    r1, g1, b1 = parse(c1)
    r2, g2, b2 = parse(c2)
    r = int(r1 + (r2 - r1) * t)
    g = int(g1 + (g2 - g1) * t)
    b = int(b1 + (b2 - b1) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def _set_window_transparent(hwnd):
    """
    使用 Win32 API 设置窗口分层透明（LWA_COLORKEY）。
    窗口中所有 #010203 颜色的像素会被系统剔除，实现真正透明。
    返回是否成功。
    """
    try:
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        LWA_COLORKEY = 0x00000001
        user32 = ctypes.windll.user32

        # 修正 SetWindowLongW 返回值/参数类型，避免 64 位截断
        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]

        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _ui_log(f"SetWindowTransparent: exstyle before=0x{exstyle:x}")
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle | WS_EX_LAYERED)

        # color key 0x00030102 -> RGB(0x01, 0x02, 0x03) = #010203
        result = user32.SetLayeredWindowAttributes(hwnd, 0x00030102, 0, LWA_COLORKEY)
        _ui_log(f"SetWindowTransparent: SetLayeredWindowAttributes returned {result}")

        # 验证样式确实设置成功
        new_exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        _ui_log(f"SetWindowTransparent: exstyle after=0x{new_exstyle:x}")
        return bool(result) and (new_exstyle & WS_EX_LAYERED)
    except Exception as exc:
        _ui_log(f"SetWindowTransparent EXCEPTION: {type(exc).__name__}: {exc}")
        return False


def _set_window_alpha(hwnd, alpha=180):
    """
    使用 Win32 API 设置窗口整体半透明（LWA_ALPHA）。
    alpha: 0-255，255 为不透明。
    返回是否成功。
    """
    try:
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        LWA_ALPHA = 0x00000002
        user32 = ctypes.windll.user32

        user32.SetWindowLongW.restype = ctypes.c_long
        user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]

        exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, exstyle | WS_EX_LAYERED)

        result = user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
        return bool(result)
    except Exception as exc:
        _ui_log(f"SetWindowAlpha EXCEPTION: {type(exc).__name__}: {exc}")
        return False


def _set_window_acrylic_mica(hwnd, backdrop=3):
    """
    调用 Windows DWM API 设置窗口背景为 Acrylic/Mica。
    backdrop: 2=Mica, 3=Acrylic, 4=Mica Alt。
    返回是否成功。
    """
    try:
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        dwmapi = ctypes.windll.dwmapi
        dark = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark),
            ctypes.sizeof(dark),
        )
        backdrop_type = ctypes.c_int(backdrop)
        dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(backdrop_type),
            ctypes.sizeof(backdrop_type),
        )
        return True
    except Exception:
        return False


def main():
    app = UsageWidget()
    app.mainloop()


if __name__ == "__main__":
    main()
