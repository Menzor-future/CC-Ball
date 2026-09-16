# Key 用量面板

一个 Windows 桌面悬浮窗，实时显示你 cc-switch 里配置的 AI key 余额/用量。纯标准库，零第三方依赖。

## 功能

- 自动读取 `~/.cc-switch/cc-switch.db` 中的 Claude providers，按 token 去重展示
- DeepSeek：显示实时人民币余额
- Kimi：显示账号昵称/等级/ID 尾号（官方未开放额度接口，所以显示"额度不可查"）
- 当前使用的 provider 带蓝色「当前使用」角标
- 底部展示今日 / 本周平台级 token 消耗（按 model 名前缀聚合；**无法按 key 拆分**，cc-switch 本地数据不支持）
- 自动每 5 分钟刷新；点击右上角 ⟳ 手动刷新
- 拖动窗口后自动记忆位置，下次启动恢复

## 安装与运行

1. 确保已安装 Python 3.9+（Windows 商店版或官方版均可，需带 tkinter）。
2. 克隆/拷贝本项目到任意目录。
3. 双击 `app.pyw` 即可启动，无黑框。

或者命令行：

```powershell
pythonw app.pyw
```

## 配置（可选）

编辑 `keymon/config.py`：

| 常量 | 说明 | 默认值 |
|---|---|---|
| `PROXY_URL` | HTTP 代理地址，留空则直连 | `http://127.0.0.1:7890` |
| `REFRESH_INTERVAL_S` | 自动刷新间隔（秒） | `300` |
| `LOW_BALANCE_CNY` | DeepSeek 余额低于该值卡片变橙色 | `5.0` |

用户数据（窗口位置）保存在 `%LOCALAPPDATA%\key-usage-widget\config.json`。

## 已知限制

- 不显示 Claude 官方订阅的「五小时 / 七天」用量（需要已登录 Claude Code 的 OAuth token）。如需可后续扩展。
- Kimi 账号余额/额度暂无公开 API，只能展示账号信息。
- 平台级消耗统计依赖 cc-switch 的 `proxy_request_logs`；如果 cc-switch 关闭 session_log 同步，该数据可能为空或滞后。

## 安全说明

- 密钥只从 cc-switch 数据库只读加载，**不会写入任何新文件**，也**不会回显到日志**。
- 网络查询仅发送给对应平台的官方 API。

## 开发/调试

```bash
# 查看从 cc-switch 读到了哪些 key
python -m keymon.ccdb

# 测试各 key 的余额/账号查询
python -m keymon.quota

# 带控制台启动 UI，便于看报错
python app.pyw
```
