# -*- coding: utf-8 -*-
"""全局配置：路径、网络、阈值、用户配置读写。"""
import json
import os

APP_DIR_NAME = "key-usage-widget"

# ---- cc-switch（key 的单一事实来源，全程只读）----
CC_SWITCH_DIR = os.path.join(os.path.expanduser("~"), ".cc-switch")
CC_SWITCH_DB = os.path.join(CC_SWITCH_DIR, "cc-switch.db")
CC_SWITCH_SETTINGS = os.path.join(CC_SWITCH_DIR, "settings.json")

# ---- 网络 ----
PROXY_URL = "http://127.0.0.1:7890"  # Clash；留空字符串则直连
HTTP_TIMEOUT_S = 10

# ---- 行为 ----
REFRESH_INTERVAL_S = 60    # 自动刷新间隔（秒）
LOW_BALANCE_CNY = 5.0      # DeepSeek 余额低于该值卡片变橙提醒

# ---- UI ----
WINDOW_ALPHA = 0.90        # 背景不透明度（0.0-1.0）

# ---- 用户配置（窗口位置等，可写）----
USER_CONFIG_PATH = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~")),
    APP_DIR_NAME, "config.json",
)

DEFAULT_USER_CONFIG = {
    "geometry": None,  # 窗口位置尺寸，如 "320x400+100+100"
    "mode": "orb",     # "orb" 圆球 / "table" 展开列表
}


def load_user_config():
    """读取用户配置；文件缺失或损坏时返回默认值。"""
    cfg = dict(DEFAULT_USER_CONFIG)
    try:
        with open(USER_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cfg.update({k: v for k, v in data.items() if k in DEFAULT_USER_CONFIG})
    except (OSError, ValueError):
        pass
    return cfg


def save_user_config(cfg):
    """原子写入用户配置，避免中途掉电产生半截 JSON。"""
    os.makedirs(os.path.dirname(USER_CONFIG_PATH), exist_ok=True)
    tmp = USER_CONFIG_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    os.replace(tmp, USER_CONFIG_PATH)
