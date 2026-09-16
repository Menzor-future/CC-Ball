# -*- coding: utf-8 -*-
"""并发查询每个 key 的余额/账号信息。全程不输出密钥。"""
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
            "User-Agent": "key-usage-widget/0.1 (readonly)",
            "Accept": "application/json",
        },
    )
    with _opener.open(req, timeout=HTTP_TIMEOUT_S) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def query_deepseek_balance(token):
    """查询 DeepSeek 余额，返回 dict 或带 error 字段。"""
    try:
        start = time.time()
        data = _request("https://api.deepseek.com/user/balance", token)
        elapsed = time.time() - start
        infos = data.get("balance_infos", [])
        if not infos:
            return {"error": "balance_infos empty", "raw": data}
        # 只展示 CNY；无 CNY 取第一条
        cny = next((b for b in infos if b.get("currency") == "CNY"), infos[0])
        return {
            "available": bool(data.get("is_available")),
            "currency": cny.get("currency", "?"),
            "balance": cny.get("total_balance", "0"),
            "granted": cny.get("granted_balance", "0"),
            "topped_up": cny.get("topped_up_balance", "0"),
            "elapsed_ms": round(elapsed * 1000, 1),
        }
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            body = ""
        return {"error": f"HTTP {exc.code}", "detail": body}
    except Exception as exc:
        return {"error": type(exc).__name__, "detail": str(exc)[:200]}


def query_kimi_account(token):
    """查询 Kimi 账号信息，返回 dict 或带 error 字段。"""
    try:
        start = time.time()
        data = _request("https://api.kimi.com/coding/v1/me", token)
        elapsed = time.time() - start
        return {
            "nickname": data.get("nickname", "").strip() or None,
            "level": data.get("user_level"),
            "level_name": data.get("user_level_name"),
            "user_id": data.get("user_id"),
            "status": data.get("status"),
            "elapsed_ms": round(elapsed * 1000, 1),
        }
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read().decode("utf-8", "replace")[:200]
        except Exception:
            body = ""
        return {"error": f"HTTP {exc.code}", "detail": body}
    except Exception as exc:
        return {"error": type(exc).__name__, "detail": str(exc)[:200]}


def query_provider(key):
    """根据 key 类型分发到对应查询。"""
    ptype = key.get("provider_type", "custom")
    if ptype == "deepseek":
        return query_deepseek_balance(key["token"])
    if ptype == "kimi":
        return query_kimi_account(key["token"])
    return {"error": f"unsupported provider type: {ptype}"}


class QuotaCache:
    """线程安全的查询结果缓存。"""

    def __init__(self, ttl_s=60):
        self._lock = threading.Lock()
        self._ttl = ttl_s
        self._data = {}
        self._timestamp = {}

    def get(self, token_tail):
        with self._lock:
            ts = self._timestamp.get(token_tail, 0)
            if time.time() - ts < self._ttl:
                return self._data.get(token_tail)
            return None

    def set(self, token_tail, value):
        with self._lock:
            self._data[token_tail] = value
            self._timestamp[token_tail] = time.time()


def fetch_all(keys, cache=None):
    """并发查询所有 keys，返回 dict{token_tail: result}。

    若提供 cache，会在返回前写入 cache；调用方可先查缓存减少请求。
    """
    results = {}
    lock = threading.Lock()

    def worker(key):
        res = query_provider(key)
        with lock:
            results[key["token_tail"]] = res
            if cache is not None:
                cache.set(key["token_tail"], res)

    threads = [threading.Thread(target=worker, args=(k,), daemon=True) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=HTTP_TIMEOUT_S + 2)

    return results


# ---- 自测入口 ----
if __name__ == "__main__":
    from keymon.ccdb import read_keys

    keys = read_keys().get("keys", [])
    cache = QuotaCache(ttl_s=300)
    results = fetch_all(keys, cache=cache)
    for k in keys:
        tail = k["token_tail"]
        print(f"\n{k['name']} ({k['provider_type']}, {tail}):")
        print(" ", results.get(tail))
    print("\ncache keys:", list(cache._data.keys()))
