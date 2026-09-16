# -*- coding: utf-8 -*-
"""冒烟测试：不弹窗，验证数据读取与 quota 查询。"""
import sys

sys.path.insert(0, r"D:\Mings_Project\key-usage-widget")

from keymon.ccdb import platform_usage, read_keys
from keymon.quota import fetch_all


def main():
    keys_info = read_keys()
    assert not keys_info["error"], keys_info["error"]
    keys = keys_info["keys"]
    assert len(keys) == 4, f"expected 4 keys, got {len(keys)}"

    # 当前 provider 必须匹配 settings
    current = [k for k in keys if k["is_current"]]
    assert len(current) == 1, f"expected exactly 1 current key, got {len(current)}"
    print(f"current key: {current[0]['name']} tail={current[0]['token_tail']}")

    # 类型分布
    ptypes = {k["provider_type"]: 0 for k in keys}
    for k in keys:
        ptypes[k["provider_type"]] += 1
    assert ptypes.get("deepseek") == 1, ptypes
    assert ptypes.get("kimi") == 3, ptypes

    # 并发查询
    results = fetch_all(keys)
    deepseek = next(k for k in keys if k["provider_type"] == "deepseek")
    ds_res = results[deepseek["token_tail"]]
    assert "error" not in ds_res, ds_res
    assert float(ds_res["balance"]) >= 0
    print(f"deepseek balance: {ds_res['balance']} {ds_res['currency']}")

    for k in keys:
        if k["provider_type"] == "kimi":
            res = results[k["token_tail"]]
            assert "error" not in res, res
            assert res.get("level_name")
            print(f"kimi {k['token_tail']}: {res['nickname']} / {res['level_name']}")

    # 用量统计
    today = platform_usage(24)
    week = platform_usage(168)
    assert not today["error"]
    assert not week["error"]
    print(f"today tokens: {today['total_tokens']:,}")
    print(f"week tokens: {week['total_tokens']:,}")

    print("\nSMOKE PASSED")


if __name__ == "__main__":
    main()
