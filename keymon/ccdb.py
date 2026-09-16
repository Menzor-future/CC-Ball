# -*- coding: utf-8 -*-
"""只读访问 cc-switch 数据库：提取 provider 配置、默认模型、当前 provider。"""
import json
import sqlite3

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


def _infer_provider_type(base_url):
    host = base_url.lower()
    if "deepseek" in host:
        return "deepseek"
    if "kimi" in host:
        return "kimi"
    if "anthropic" in host:
        return "anthropic"
    return "custom"


def _get_default_model(env):
    """从 env 中读取默认模型，优先 Fable，其次 Haiku/Opus。"""
    for key in (
        "ANTHROPIC_DEFAULT_FABLE_MODEL",
        "ANTHROPIC_DEFAULT_HAIKU_MODEL",
        "ANTHROPIC_DEFAULT_OPUS_MODEL",
    ):
        val = env.get(key, "").strip()
        if val:
            return val
    return "-"


def read_providers():
    """读取每个 provider 配置一行。

    返回 {"error": str|None, "providers": list[dict]}。
    """
    current_id = get_current_provider_id()
    try:
        con = sqlite3.connect(f"file:{CC_SWITCH_DB}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        return {"error": f"open db failed: {exc}", "providers": []}

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

    providers = []
    for row in rows:
        cfg = json.loads(row["settings_config"] or "{}")
        env = cfg.get("env", cfg) if isinstance(cfg, dict) else {}
        token = env.get("ANTHROPIC_AUTH_TOKEN", "").strip()
        base_url = env.get("ANTHROPIC_BASE_URL", "").strip().rstrip("/")
        if not token or not base_url:
            continue

        providers.append({
            "id": row["id"],
            "name": row["name"],
            "token_tail": _masked_key_tail(token),
            "token": token,
            "base_url": base_url,
            "provider_type": _infer_provider_type(base_url),
            "model": _get_default_model(env),
            "is_current": row["id"] == current_id,
        })

    return {"error": None, "providers": providers}


# ---- 自测入口 ----
if __name__ == "__main__":
    print("current provider id:", get_current_provider_id())
    data = read_providers()
    if data["error"]:
        print("error:", data["error"])
    for p in data["providers"]:
        print(
            f"  [{p['provider_type']:10}] {p['name']:22} "
            f"model={p['model']:18} current={p['is_current']} tail={p['token_tail']}"
        )
