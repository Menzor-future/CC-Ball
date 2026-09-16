# -*- coding: utf-8 -*-
"""冒烟测试：不弹窗，验证 provider 读取与 quota 查询。"""
import sys

sys.path.insert(0, r"D:\Mings_Project\key-usage-widget")

from keymon.ccdb import read_providers
from keymon.quota import fetch_all


def main():
    data = read_providers()
    assert not data["error"], data["error"]
    providers = data["providers"]
    assert len(providers) >= 1, "expected at least one provider"

    current = [p for p in providers if p["is_current"]]
    assert len(current) == 1, f"expected exactly 1 current provider, got {len(current)}"
    print(f"current provider: {current[0]['name']} model={current[0]['model']}")

    results = fetch_all(providers)
    for p in providers:
        res = results[p["id"]]
        if p["provider_type"] == "kimi":
            assert "error" not in res, res
            assert isinstance(res.get("h5_remaining"), float)
            assert isinstance(res.get("d7_remaining"), float)
            print(
                f"[kimi] {p['name']:22} {p['model']:18} "
                f"5h={res['h5_remaining']*100:.0f}% 7d={res['d7_remaining']*100:.0f}%"
            )
        elif p["provider_type"] == "deepseek":
            assert "error" not in res, res
            assert float(res["balance"]) >= 0
            print(f"[deepseek] {p['name']:22} {p['model']:18} balance={res['balance']} {res['currency']}")
        else:
            print(f"[{p['provider_type']}] {p['name']:22} {p['model']:18} -> {res}")

    print("\nSMOKE PASSED")


if __name__ == "__main__":
    main()
