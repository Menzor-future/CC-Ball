# -*- coding: utf-8 -*-
"""悬浮窗 UI：半透明表格，展示 商名 | 模型 | 5h | 7day。"""
import datetime as dt
import threading
import tkinter as tk
from tkinter import font as tkfont

from .config import (
    LOW_BALANCE_CNY,
    REFRESH_INTERVAL_S,
    WINDOW_ALPHA,
    load_user_config,
    save_user_config,
)
from .ccdb import read_providers
from .quota import QuotaCache, fetch_all

# 配色（深色玻璃风）
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

COLS = ["商名", "模型", "5h", "7day"]
COL_WIDTHS = [120, 130, 95, 95]


class UsageWidget(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Key 用量面板")
        self.configure(bg=BG)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", WINDOW_ALPHA)
        self.resizable(False, False)

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

        self._restore_geometry()
        self.refresh()

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
        # 宽度 = 列宽和 + 边距; 高度由行数决定，先给个最小值
        width = sum(COL_WIDTHS) + 16 + 2  # 16 pad, 1px grid borders approx
        self.geometry(f"{width}x160+80+80")

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
        # 清旧行
        for row_cells in self._rows:
            for cell in row_cells:
                cell.destroy()
        self._rows.clear()

        if error:
            self._render_error(error)
            return
        if not providers:
            self._render_error("未找到 provider 配置")
            return

        for row_idx, provider in enumerate(providers, start=1):
            self._render_provider_row(row_idx, provider, results.get(provider["id"], {}))

        # 自适应高度
        height = 60 + len(providers) * 28
        width = sum(COL_WIDTHS) + 18
        geo = self.geometry()
        pos = geo.split("+", 1)[1] if "+" in geo else "80+80"
        self.geometry(f"{width}x{height}+{pos}")

        import datetime
        self.updated_label.config(text=f"更新于 {datetime.datetime.now().strftime('%H:%M:%S')}")

    def _render_provider_row(self, row_idx, provider, res):
        is_current = provider["is_current"]
        bg = BG_CURRENT if is_current else BG
        font = self.font_body_bold if is_current else self.font_body
        cells = []

        # 商名
        cells.append(self._cell(row_idx, 0, provider["name"], bg, font=font, anchor="w"))
        # 模型
        cells.append(self._cell(row_idx, 1, provider["model"], bg, font=font, anchor="w", fg=TEXT_DIM))

        ptype = provider["provider_type"]
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
            # 占位，保持列表长度一致
            cells.append(None)
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
                self._fmt_pct(d7, res.get("d7_reset")), bg, font=font,
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
    def _fmt_pct(value, reset_time=None):
        pct = UsageWidget._fmt_pct_raw(value)
        if value is None or not reset_time:
            return pct
        return f"{pct} ({UsageWidget._fmt_countdown(reset_time)})"

    @staticmethod
    def _fmt_pct_raw(value):
        if value is None:
            return "N/A"
        return f"{max(0.0, min(1.0, value)) * 100:.0f}%"

    @staticmethod
    def _fmt_countdown(reset_time):
        """把 ISO reset_time 格式化为剩余时间，如 2h15m / 1d3h / expired。"""
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


def main():
    app = UsageWidget()
    app.mainloop()


if __name__ == "__main__":
    main()
