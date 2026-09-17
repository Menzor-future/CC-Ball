# Key 用量面板

一个 Windows 桌面悬浮窗，实时显示 cc-switch 里每个 provider 的余额/用量。纯标准库，零第三方依赖。

## 功能

- 自动读取 `~/.cc-switch/cc-switch.db` 中的 Claude providers，**每个 provider 配置一行**
- 默认显示一个 **圆形仪表盘**，展示当前选中配置的 5h 已用量百分比；点击圆球以动画展开完整方形列表
- 展开动画：圆球文字渐隐 → 透黑圆形扩张为方形 → 列表文字渐显
- Windows 11 Acrylic/Mica 磨砂玻璃背景，**文字 100% 不透明**
- 紧凑表格布局：账号名 | 模型 | 5h | 7day
- **Kimi For Coding**：账号名显示 `/v1/me` 返回的昵称；5h 显示剩余用量百分比 + 重置倒计时（如 `76%(2h15m)`），7day 显示剩余百分比 + 简化倒计时（如 `70%(5d)`）
- **DeepSeek**：账号名固定显示 `DeepSeek`，余额合并显示在 5h/7day 两列
- **Claude Official**：账号名固定显示 `Claude`；5h/7day 预留，需要 Claude Code 登录后的 OAuth token（本机未登录时显示 `N/A`）
- 当前使用的 provider 行文字加粗 + 背景高亮
- 每分钟自动刷新；展开状态下 footer 左侧 ⟳ 可手动刷新，右侧 ✕ 收起回圆球
- 拖动窗口后自动记忆位置与展开/收起状态

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
| `PROXY_URL` | 备用代理地址。直连优先；仅当直连出现连接被拒/超时/DNS 失败时回退到此代理重试，留空则永远直连 | `http://127.0.0.1:7890` |
| `REFRESH_INTERVAL_S` | 自动刷新间隔（秒） | `60` |
| `LOW_BALANCE_CNY` | DeepSeek 余额低于该值变橙色提醒 | `5.0` |
| `WINDOW_ALPHA` | 背景不透明度（0.0–1.0），DWM 不可用时作为 fallback | `0.90` |

用户数据（窗口位置、orb/table 模式）保存在 `%LOCALAPPDATA%\key-usage-widget\config.json`。

## 数据源

| Provider | 5h/7day | 余额 |
|---|---|---|
| Kimi For Coding | `GET https://api.kimi.com/coding/v1/usages` | 无 |
| DeepSeek | 无官方接口 | `GET https://api.deepseek.com/user/balance` |
| Claude Official | `https://api.anthropic.com/api/oauth/usage`（需 OAuth） | 不适用 |

## 已知限制

- Claude Official 的 5h/7day 需要本机已登录 Claude Code；当前未检测登录态时会显示 `N/A`。
- Kimi 只展示 5h/7day 百分比与账号昵称，没有实时余额接口。
- DeepSeek 没有 5h/7day 接口，余额列合并显示。

## 安全说明

- 密钥只从 cc-switch 数据库只读加载，**不会写入任何新文件**，也**不会回显到日志**。
- 网络查询仅发送给对应平台的官方 API。

## 开发/调试

```bash
# 查看从 cc-switch 读到了哪些 provider
python -m keymon.ccdb

# 测试各 provider 的用量/余额查询
python -m keymon.quota

# 数据层冒烟测试
python tests/smoke.py

# 带控制台启动 UI，便于看报错
python app.pyw
```
