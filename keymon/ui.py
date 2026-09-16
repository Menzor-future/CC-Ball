# -*- coding: utf-8 -*-
"""悬浮窗 UI：Acrylic/Mica 磨砂玻璃背景，表格展示 账号名 | 模型 | 5h | 7day。"""
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

# 诊断日志路径（仅用于排查 UI 行数/空白等问题）
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

COLS = ["账号名", "模型", "5h", "7day"]
COL_WIDTHS = [110, 120, 105, 105]


class UsageWidget(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Key 用量面板")
        self.configure(bg=BG)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.resizable(False, False)
        self.withdraw()  # 首次渲染完成前隐藏，避免默认尺寸闪现

        # 字体
        self.font_header = tkfont.Font(family="Microsoft YaHei UI", size=9, weight="bold")
        self.font_body = tkfont.Font(family="Microsoft YaHei UI", size=9)
        self.font_body_bold = tkfont.Font(family="Microsoft YaHei UI", size=9, weight="bold")
        self.font_small = tkfont.Font(family="Microsoft YaHei UI", size=8)

        # 拖动
        self._drag_x = self._drag_y = 0
        self.bind("<ButtonPress-1>", self._start_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._stop_drag)

        self._build_header()
        self._build_table()
        self._build_footer()

        self.cache = QuotaCache(ttl_s=60)
        self._refresh_in_progress = False
        self._auto_refresh_id = None
        self._first_show_pending = True  # 首次渲染完成前隐藏窗口，避免闪烁

        _reset_ui_log()
        _ui_log("UsageWidget init")

        self._restore_geometry()
        self.refresh()

    # ---- 背景 ----
    def _apply_glass_background(self):
        """Windows 11 用 DWM 设置 Acrylic/Mica；失败则退回 tkinter alpha。"""
        if not _set_window_acrylic_mica(self.winfo_id()):
            self.attributes("-alpha", WINDOW_ALPHA)

    # ---- 拖动 ----
    def _start_drag(self, event):
        self._drag_x, self._drag_y = event.x, event.y

    def _on_drag(self, event):
        x = self.winfo_x() + event.x - self._drag_x
        y = self.winfo_y() + event.y - self._drag_y
        self.geometry(f"+{x}+{y}")

    def _stop_drag(self, _event=None):
        self._save_geometry()

    # ---- 布局 ----
    def _build_header(self):
        header = tk.Frame(self, bg=BG, padx=8, pady=6)
        header.grid(row=0, column=0, sticky="ew")
        tk.Label(
            header, text="🔑 Key 用量面板", fg=TEXT, bg=BG,
            font=self.font_header,
        ).pack(side="left")

        self.refresh_btn = tk.Label(
            header, text="⟳", fg=ACCENT, bg=BG, font=self.font_header, cursor="hand2",
        )
        self.refresh_btn.pack(side="right", padx=2)
        self.refresh_btn.bind("<Button-1>", lambda _e: self.refresh())

        close = tk.Label(header, text="✕", fg=TEXT_DIM, bg=BG, font=self.font_body, cursor="hand2")
        close.pack(side="right", padx=8)
        close.bind("<Button-1>", lambda _e: self.destroy())

    def _build_table(self):
        self.table = tk.Frame(self, bg=GRID, padx=1, pady=1)
        self.table.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 6))

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

    def _build_footer(self):
        self.footer = tk.Frame(self, bg=BG, padx=8, pady=4)
        self.footer.grid(row=2, column=0, sticky="ew")
        self.updated_label = tk.Label(
            self.footer, text="", fg=TEXT_DIM, bg=BG, font=self.font_small, anchor="e",
        )
        self.updated_label.pack(fill="x")

    # ---- 几何位置 ----
    def _restore_geometry(self):
        cfg = load_user_config()
        geo = cfg.get("geometry")
        if geo:
            try:
                self.geometry(geo)
                return
            except tk.TclError:
                pass
        self._set_default_geometry()

    def _set_default_geometry(self):
        width, height = self._compute_geometry(1)
        self.geometry(f"{width}x{height}+80+80")

    def _compute_geometry(self, data_rows):
        """根据数据行数精确计算窗口宽高，避免依赖 withdraw 状态下的 winfo。"""
        cell_grid_pad_x = 1  # 单侧
        table_frame_pad_x = 8  # 单侧
        width = sum(COL_WIDTHS) + len(COL_WIDTHS) * cell_grid_pad_x * 2 + table_frame_pad_x * 2

        header_h = 36
        table_header_h = 28
        row_h = 28
        table_bottom_pad = 6
        footer_h = 28
        height = header_h + table_header_h + data_rows * row_h + table_bottom_pad + footer_h
        return width, height

    def _save_geometry(self):
        cfg = load_user_config()
        cfg["geometry"] = self.geometry()
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
                self.after(0, self._render, providers, results, error)
            finally:
                self.after(0, lambda: self.refresh_btn.config(text="⟳", fg=ACCENT))
                self._refresh_in_progress = False
                self._schedule_auto_refresh()

        threading.Thread(target=job, daemon=True).start()

    def _schedule_auto_refresh(self):
        if self._auto_refresh_id is not None:
            self.after_cancel(self._auto_refresh_id)
        self._auto_refresh_id = self.after(REFRESH_INTERVAL_S * 1000, self.refresh)

    # ---- 渲染 ----
    def _render(self, providers, results, error):
        try:
            _ui_log(f"_render start: providers={len(providers)} error={error}")
            for i, p in enumerate(providers):
                res = results.get(p["id"], {})
                _ui_log(f"  provider[{i}] id={p['id']} name={p['name']} type={p['provider_type']} has_error={'error' in res}")

            # 清旧行（防御 None 占位）
            for row_cells in self._rows:
                for cell in row_cells:
                    if cell is not None:
                        cell.destroy()
            self._rows.clear()

            if error:
                _ui_log("_render error branch")
                self._render_error(error)
                self._finalize_geometry(data_rows=2)
                return
            if not providers:
                _ui_log("_render no providers branch")
                self._render_error("未找到 provider 配置")
                self._finalize_geometry(data_rows=2)
                return

            for row_idx, provider in enumerate(providers, start=1):
                _ui_log(f"_render row {row_idx} {provider['id']}")
                self._render_provider_row(row_idx, provider, results.get(provider["id"], {}))

            _ui_log(f"_render finalize: rows_created={len(self._rows)}")
            self._finalize_geometry(data_rows=len(providers))

            self.updated_label.config(text=f"更新于 {dt.datetime.now().strftime('%H:%M:%S')}")
        except Exception as exc:
            _ui_log(f"_render EXCEPTION: {type(exc).__name__}: {exc}")
            raise

    def _finalize_geometry(self, data_rows=0):
        """根据数据行数精确设置窗口大小，避免右侧空白或高度抖动。"""
        width, height = self._compute_geometry(data_rows)
        geo = self.geometry()
        pos = geo.split("+", 1)[1] if "+" in geo else "80+80"
        _ui_log(f"_finalize_geometry: data_rows={data_rows} win={width}x{height} pos={pos}")
        self.geometry(f"{width}x{height}+{pos}")

        # 首次渲染完成后才真正显示窗口，避免默认尺寸闪过
        if self._first_show_pending:
            self._first_show_pending = False
            _ui_log("deiconify first show")
            self.deiconify()
            self._apply_glass_background()

    def _render_provider_row(self, row_idx, provider, res):
        is_current = provider["is_current"]
        bg = BG_CURRENT if is_current else BG
        font = self.font_body_bold if is_current else self.font_body
        cells = []

        ptype = provider["provider_type"]
        # 账号名：Kimi 用 /v1/me 昵称，DeepSeek 固定 DeepSeek，Claude 固定 Claude
        account_name = provider["name"]
        if ptype == "kimi":
            account_name = res.get("account_name") or provider["name"]
        elif ptype == "deepseek":
            account_name = "DeepSeek"
        elif ptype == "anthropic":
            account_name = "Claude"

        cells.append(self._cell(row_idx, 0, account_name, bg, font=font, anchor="w"))
        # 模型
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
            # 跨 5h/7day 两列
            cell = tk.Frame(self.table, bg=bg, width=COL_WIDTHS[2] + COL_WIDTHS[3] + 2, height=26)
            cell.grid(row=row_idx, column=2, columnspan=2, sticky="nsew", padx=1, pady=1)
            cell.grid_propagate(False)
            tk.Label(
                cell, text=text, fg=color, bg=bg,
                font=font, anchor="e",
            ).pack(side="right", padx=6)
            cells.append(cell)
            # DeepSeek 跨两列，后面不需要再单独放 cell
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
            # Python 3.9 fromisoformat 不支持 'Z' 后缀
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


def _set_window_acrylic_mica(hwnd, backdrop=3):
    """
    调用 Windows DWM API 设置窗口背景为 Acrylic/Mica。
    backdrop: 2=Mica, 3=Acrylic, 4=Mica Alt。
    返回是否成功。
    """
    try:
        # 优先用 DWMWA_SYSTEMBACKDROP_TYPE (Windows 11)
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_SYSTEMBACKDROP_TYPE = 38
        dwmapi = ctypes.windll.dwmapi
        # 启用沉浸式深色模式，让 Acrylic 呈深玻璃色
        dark = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd,
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark),
            ctypes.sizeof(dark),
        )
        # 设置背景类型
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
