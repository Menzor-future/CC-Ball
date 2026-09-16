# -*- coding: utf-8 -*-
"""只读访问 cc-switch 数据库：提取 key、当前 provider、平台级消耗。"""
import json
import sqlite3
import time
from collections import defaultdict

from .config import CC_SWITCH_DB, CC_SWITCH_SETTINGS


def _masked_key_tail(token):
    return f"...{token[-4:]}" if token and len(token) > 4 else token


def get_current_provider_id():
    """读取 cc-switch 当前选中的 Claude provider id。"""
    try:
        with open(CC_SWITCH_SETTINGS, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("currentProviderClaude")
    except (OSError, ValueError):
        return None


def read_keys():
    """从 providers 表读取所有 Claude app_type 的 key。

    返回 list[dict]，按 base_url + token 去重；同 token 多个配置会合并并注明"configs=N"。
    """
    current_id = get_current_provider_id()
    try:
        con = sqlite3.connect(f"file:{CC_SWITCH_DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return {"error": f"open db failed: {exc}", "keys": []}

    con.row_factory = sqlite3.Row
    cur = con.cursor()
    rows = cur.execute(
        """
        SELECT id, name, settings_config, sort_index
        FROM providers
        WHERE app_type = 'claude'
        ORDER BY sort_index
        """
    ).fetchall()

    # 按 token 聚合
    grouped = {}  # token -> {...}
    for row in rows:
        cfg = json.loads(row["settings_config"] or "{}")
        env = cfg.get("env", cfg) if isinstance(cfg, dict) else {}
        token = env.get("ANTHROPIC_AUTH_TOKEN", "").strip()
        base_url = env.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/")
        if not token or not base_url:
            continue

        is_current = (row["id"] == current_id)

        if token in grouped:
            grouped[token]["config_names"].append(row["name"])
            grouped[token]["is_current"] |= is_current
            continue

        grouped[token] = {
            "provider_id": row["id"],
            "name": row["name"],
            "config_names": [row["name"]],
            "token_tail": _masked_key_tail(token),
            "base_url": base_url,
            "token": token,
            "is_current": is_current,
            "provider_type": _infer_provider_type(base_url),
        }

    keys = list(grouped.values())
    keys.sort(key=lambda k: (not k["is_current"], k["name"].lower()))
    return {"error": None, "keys": keys}


def _infer_provider_type(base_url):
    host = base_url.lower()
    if "deepseek" in host:
        return "deepseek"
    if "kimi" in host:
        return "kimi"
    if "anthropic" in host:
        return "anthropic"
    return "custom"


def platform_usage(since_hours=None):
    """按 model 前缀聚合 proxy_request_logs 的消耗（平台级，无法按 key 拆分）。

    since_hours: None 表示全部；24/168 分别对应今日/本周。
    返回 dict: {"total_tokens": int, "by_platform": {"kimi": int, "deepseek": int, ...}}
    """
    # 实测 cc-switch 的 created_at 字段存的是秒（非毫秒）。
    now_s = int(time.time())
    since_s = 0
    if since_hours:
        since_s = now_s - since_hours * 3600

    try:
        con = sqlite3.connect(f"file:{CC_SWITCH_DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return {"error": f"open db failed: {exc}", "total_tokens": 0, "by_platform": {}}

    cur = con.cursor()
    sql = """
        SELECT model,
               COALESCE(input_tokens, 0) + COALESCE(output_tokens, 0) AS tokens
        FROM proxy_request_logs
        WHERE data_source = 'session_log'
          AND (? = 0 OR created_at >= ?)
    """
    rows = cur.execute(sql, (0 if not since_hours else 1, since_s)).fetchall()

    by_platform = defaultdict(int)
    total = 0
    for model, tokens in rows:
        platform = _model_to_platform(model)
        by_platform[platform] += tokens
        total += tokens

    return {"error": None, "total_tokens": total, "by_platform": dict(by_platform)}


def _model_to_platform(model):
    if not model:
        return "other"
    m = model.lower()
    if "kimi" in m:
        return "kimi"
    if "deepseek" in m:
        return "deepseek"
    if "claude" in m or "opus" in m or "sonnet" in m or "fable" in m or "haiku" in m:
        return "anthropic"
    return "other"


# ---- 自测入口 ----
if __name__ == "__main__":
    print("当前 provider id:", get_current_provider_id())
    keys = read_keys()
    print("\nkeys:")
    for k in keys.get("keys", []):
        print(
            f"  [{k['provider_type']:10}] {k['name']:22} tail={k['token_tail']} "
            f"current={k['is_current']} configs={len(k['config_names'])} base={k['base_url']}"
        )
    for hours, label in [(24, "今日"), (168, "本周")]:
        u = platform_usage(hours)
        print(f"\n{label} (按平台聚合): total={u['total_tokens']:,} {u['by_platform']}")
