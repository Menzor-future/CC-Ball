# -*- coding: utf-8 -*-
"""悬浮窗 UI：深色卡片、可拖动、置顶、手动刷新。"""
import threading
import tkinter as tk
from tkinter import font as tkfont

from .config import LOW_BALANCE_CNY, REFRESH_INTERVAL_S, load_user_config, save_user_config
from .ccdb import platform_usage, read_keys
from .quota import QuotaCache, fetch_all

# 配色（深色玻璃风）
BG = "#1e1e24"
CARD_BG = "#2a2a32"
CARD_CURRENT = "#3a2f22"
TEXT = "#e8e8ec"
TEXT_DIM = "#9a9aa3"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
ORANGE = "#d29922"
RED = "#f85149"


class UsageWidget(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Key 用量面板")
        self.configure(bg=BG)
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.97)
        self.resizable(False, False)

        # 拖动状态
        self._drag_x = self._drag_y = 0
        self.bind("<ButtonPress-1>", self._start_drag)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._stop_drag)

        # 字体
        self.font_title = tkfont.Font(family="Microsoft YaHei UI", size=10, weight="bold")
        self.font_body = tkfont.Font(family="Microsoft YaHei UI", size=9)
        self.font_small = tkfont.Font(family="Microsoft YaHei UI", size=8)

        self._build_header()
        self._build_cards_container()
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
        header = tk.Frame(self, bg=BG, padx=10, pady=8)
        header.pack(fill="x")
        tk.Label(
            header, text="🔑 Key 用量面板", fg=TEXT, bg=BG,
            font=self.font_title,
        ).pack(side="left")
        self.refresh_btn = tk.Label(
            header, text="⟳", fg=ACCENT, bg=BG, font=self.font_title, cursor="hand2",
        )
        self.refresh_btn.pack(side="right", padx=2)
        self.refresh_btn.bind("<Button-1>", lambda _e: self.refresh())

        close = tk.Label(header, text="✕", fg=TEXT_DIM, bg=BG, font=self.font_body, cursor="hand2")
        close.pack(side="right", padx=8)
        close.bind("<Button-1>", lambda _e: self.destroy())

    def _build_cards_container(self):
        self.cards_frame = tk.Frame(self, bg=BG, padx=10)
        self.cards_frame.pack(fill="both", expand=True, pady=6)
        self._card_widgets = []

    def _build_footer(self):
        self.footer = tk.Frame(self, bg=BG, padx=10, pady=6)
        self.footer.pack(fill="x")
        self.usage_label = tk.Label(
            self.footer, text="加载中…", fg=TEXT_DIM, bg=BG, font=self.font_small,
            justify="left", anchor="w",
        )
        self.usage_label.pack(fill="x")
        self.updated_label = tk.Label(
            self.footer, text="", fg=TEXT_DIM, bg=BG, font=self.font_small,
            anchor="e",
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
        self.geometry("320x380+80+80")

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
                keys_info = read_keys()
                keys = keys_info.get("keys", [])
                error = keys_info.get("error")
                results = fetch_all(keys, cache=self.cache) if not error and keys else {}
                usage_today = platform_usage(24)
                usage_week = platform_usage(168)
                self.after(0, self._render, keys, results, error, usage_today, usage_week)
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
    def _render(self, keys, results, error, usage_today, usage_week):
        # 清旧卡片
        for w in self._card_widgets:
            w.destroy()
        self._card_widgets.clear()

        if error:
            self._add_card("读取 cc-switch 失败", error, RED)
            return
        if not keys:
            self._add_card("未找到 key", "请检查 cc-switch 的 Claude providers", TEXT_DIM)
            return

        for key in keys:
            self._render_key_card(key, results.get(key["token_tail"], {}))

        self._render_footer(usage_today, usage_week)

    def _render_key_card(self, key, res):
        is_current = key["is_current"]
        card = tk.Frame(
            self.cards_frame, bg=CARD_CURRENT if is_current else CARD_BG,
            padx=10, pady=8,
        )
        card.pack(fill="x", pady=8)
        self._card_widgets.append(card)

        # 标题行
        title_row = tk.Frame(card, bg=card["bg"])
        title_row.pack(fill="x")
        name = key["name"]
        if len(key["config_names"]) > 1:
            name = f"{name}（{len(key['config_names'])} 个配置共用）"
        tk.Label(
            title_row, text=name, fg=TEXT, bg=card["bg"],
            font=self.font_body,
        ).pack(side="left")
        if is_current:
            tk.Label(
                title_row, text="当前使用", fg=BG, bg=ACCENT,
                font=self.font_small, padx=4, pady=1,
            ).pack(side="right")

        # 内容行
        ptype = key["provider_type"]
        if "error" in res:
            status_text = f"查询失败：{res['error']}"
            status_color = RED
            detail = res.get("detail", "")
            if detail:
                status_text += f"\n{detail}"
        elif ptype == "deepseek":
            try:
                bal = float(res.get("balance", "0"))
            except ValueError:
                bal = 0.0
            status_text = f"余额：¥{res.get('balance', '--')} {res.get('currency', '')}"
            if bal < LOW_BALANCE_CNY:
                status_color = ORANGE
            else:
                status_color = GREEN
        elif ptype == "kimi":
            nickname = res.get("nickname") or "未知昵称"
            level = res.get("level_name") or f"Lv.{res.get('level', '?')}"
            uid_tail = (res.get("user_id") or "-")[-6:]
            status_text = f"{nickname} · {level}\nID 尾号 {uid_tail}"
            status_color = TEXT
        else:
            status_text = "暂不支持查询"
            status_color = TEXT_DIM

        lbl = tk.Label(
            card, text=status_text, fg=status_color, bg=card["bg"],
            font=self.font_small, justify="left", anchor="w",
        )
        lbl.pack(fill="x", pady=4)

    def _render_footer(self, today, week):
        err = today.get("error") or week.get("error")
        if err:
            self.usage_label.config(text=f"用量统计失败：{err}", fg=RED)
        else:
            t = today.get("total_tokens", 0)
            w = week.get("total_tokens", 0)
            by_t = today.get("by_platform", {})
            by_w = week.get("by_platform", {})
            text = (
                f"今日 {self._fmt_tokens(t)}"
                f"｜本周 {self._fmt_tokens(w)}\n"
                f"按平台合计：{self._fmt_by(by_t)} / {self._fmt_by(by_w)}\n"
                f"无法按 key 拆分"
            )
            self.usage_label.config(text=text, fg=TEXT_DIM)
        import datetime
        self.updated_label.config(text=f"更新于 {datetime.datetime.now().strftime('%H:%M:%S')}")

    @staticmethod
    def _fmt_tokens(n):
        if n >= 1_000_000:
            return f"{n / 1_000_000:.2f}M"
        if n >= 1_000:
            return f"{n / 1_000:.1f}K"
        return str(n)

    @staticmethod
    def _fmt_by(by):
        if not by:
            return "—"
        return ", ".join(f"{k} {UsageWidget._fmt_tokens(v)}" for k, v in by.items())

    def _add_card(self, title, body, color):
        card = tk.Frame(self.cards_frame, bg=CARD_BG, padx=10, pady=8)
        card.pack(fill="x", pady=8)
        self._card_widgets.append(card)
        tk.Label(card, text=title, fg=color, bg=CARD_BG, font=self.font_body).pack(anchor="w")
        tk.Label(card, text=body, fg=TEXT_DIM, bg=CARD_BG, font=self.font_small, justify="left").pack(anchor="w", pady=4)


def main():
    app = UsageWidget()
    app.mainloop()


if __name__ == "__main__":
    main()
