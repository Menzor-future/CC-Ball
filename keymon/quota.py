# -*- coding: utf-8 -*-
"""并发查询每个 provider 的用量/余额。全程不输出密钥。"""
import json
import threading
import time
import urllib.error
import urllib.request
from collections import namedtuple

from .config import HTTP_TIMEOUT_S, PROXY_URL

KeyInfo = namedtuple("KeyInfo", ["key", "result", "elapsed"])


def _build_opener():
    if PROXY_URL:
        handler = urllib.request.ProxyHandler({"http": PROXY_URL, "https": PROXY_URL})
        return urllib.request.build_opener(handler)
    return urllib.request.build_opener()


_opener = _build_opener()


def _request(url, token):
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "User-Agent": "key-usage-widget/0.2 (readonly)",
            "Accept": "application/json",
        },
    )
    with _opener.open(req, timeout=HTTP_TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _fmt_error(exc):
    if isinstance(exc, urllib.error.HTTPError):
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            body = ""
        return {"error": f"HTTP {exc.code}", "detail": body}
    return {"error": type(exc).__name__, "detail": str(exc)[:200]}


def query_kimi_usages(token):
    """查询 Kimi 5h/7day 用量与账号昵称，返回剩余百分比、reset 时间、account_name。"""
    start = time.time()
    results = {"usages": None, "me": None}
    errors = []
    lock = threading.Lock()

    def fetch_usages():
        try:
            results["usages"] = _request("https://api.kimi.com/coding/v1/usages", token)
        except Exception as exc:
            with lock:
                errors.append(_fmt_error(exc))

    def fetch_me():
        try:
            results["me"] = _request("https://api.kimi.com/coding/v1/me", token)
        except Exception:
            # 账号名非关键，失败可忽略
            pass

    threads = [threading.Thread(target=fetch_usages), threading.Thread(target=fetch_me)]
    for t in threads:
        t.daemon = True
        t.start()
    for t in threads:
        t.join(timeout=HTTP_TIMEOUT_S + 2)

    if errors:
        return errors[0]
    if results["usages"] is None:
        return {"error": "usages request failed"}

    usages = results["usages"].get("usages", {})
    h5 = usages.get("limit_5h", {})
    d7 = usages.get("limit_7d", {})

    def remaining(ratio):
        try:
            return max(0.0, 1.0 - float(ratio))
        except (TypeError, ValueError):
            return None

    account_name = None
    if results["me"]:
        raw = results["me"].get("nickname", "").strip()
        if raw:
            account_name = raw

    return {
        "account_name": account_name,
        "h5_remaining": remaining(h5.get("used_ratio")),
        "h5_reset": h5.get("reset_time"),
        "d7_remaining": remaining(d7.get("used_ratio")),
        "d7_reset": d7.get("reset_time"),
        "elapsed_ms": round((time.time() - start) * 1000, 1),
    }


def query_deepseek_balance(token):
    """查询 DeepSeek 余额，返回 dict 或带 error 字段。"""
    try:
        start = time.time()
        data = _request("https://api.deepseek.com/user/balance", token)
        elapsed = time.time() - start
        infos = data.get("balance_infos", [])
        if not infos:
            return {"error": "balance_infos empty", "raw": data}
        cny = next((b for b in infos if b.get("currency") == "CNY"), infos[0])
        return {
            "available": bool(data.get("is_available")),
            "currency": cny.get("currency", "?"),
            "balance": cny.get("total_balance", "0"),
            "granted": cny.get("granted_balance", "0"),
            "topped_up": cny.get("topped_up_balance", "0"),
            "elapsed_ms": round(elapsed * 1000, 1),
        }
    except Exception as exc:
        return _fmt_error(exc)


def query_claude_usage(oauth_token):
    """Claude Official 5h/7day 预留；当前无 OAuth token 时返回 N/A。"""
    if not oauth_token:
        return {"error": "no OAuth token"}
    # 预留：未来实现 /api/oauth/usage 解析
    return {"error": "not implemented"}


def query_provider(provider, oauth_token=None):
    """根据 provider 类型分发到对应查询。"""
    ptype = provider.get("provider_type", "custom")
    if ptype == "kimi":
        return query_kimi_usages(provider["token"])
    if ptype == "deepseek":
        return query_deepseek_balance(provider["token"])
    if ptype == "anthropic":
        return query_claude_usage(oauth_token)
    return {"error": f"unsupported provider type: {ptype}"}


class QuotaCache:
    """线程安全的查询结果缓存，key 为 provider id。"""

    def __init__(self, ttl_s=60):
        self._lock = threading.Lock()
        self._ttl = ttl_s
        self._data = {}
        self._timestamp = {}

    def get(self, pid):
        with self._lock:
            ts = self._timestamp.get(pid, 0)
            if time.time() - ts < self._ttl:
                return self._data.get(pid)
            return None

    def set(self, pid, value):
        with self._lock:
            self._data[pid] = value
            self._timestamp[pid] = time.time()


def fetch_all(providers, cache=None, oauth_token=None):
    """并发查询所有 providers，返回 dict{id: result}。"""
    results = {}
    lock = threading.Lock()

    def worker(provider):
        res = query_provider(provider, oauth_token=oauth_token)
        with lock:
            results[provider["id"]] = res
            if cache is not None:
                cache.set(provider["id"], res)

    threads = [threading.Thread(target=worker, args=(p,), daemon=True) for p in providers]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=HTTP_TIMEOUT_S + 2)

    return results


# ---- 自测入口 ----
if __name__ == "__main__":
    from keymon.ccdb import read_providers

    providers = read_providers().get("providers", [])
    cache = QuotaCache(ttl_s=300)
    results = fetch_all(providers, cache=cache)
    for p in providers:
        rid = p["id"]
        print(f"\n{p['name']} ({p['provider_type']}, {p['token_tail']}):")
        print(" ", results.get(rid))
    print("\ncache keys:", list(cache._data.keys()))
