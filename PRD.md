# PRD：Key 用量悬浮面板（key-usage-widget）

> 状态：已完成（2026-09-16）
> 日期：2026-09-16

## 1. 背景与目标

桌面上放一个置顶小悬浮窗，随时查看手里几把 AI key 的余额/用量，不用每次都打开 cc-switch。

## 2. 前期调研结论（全部本机实测）

| key 类型 | 数据源 | 实测结果 |
|---|---|---|
| DeepSeek | `GET https://api.deepseek.com/user/balance`（Bearer key） | ✅ 返回 `{"is_available":true,"balance_infos":[{"currency":"CNY","total_balance":"6.25",...}]}` |
| Kimi For Coding | `GET https://api.kimi.com/coding/v1/me` | ✅ 返回昵称 / 等级（Allegro、Allegretto…）/ 脱敏手机号 / user_id |
| Kimi For Coding | quota / balance / usage / subscription / plan / rate_limits / entitlement | ❌ 全部 404，官方未开放额度查询 |
| Claude 官方订阅 | `https://api.anthropic.com/api/oauth/usage` | 本机无登录态（无 `.credentials.json`，凭据管理器无记录）。**按阿泽决定：v1 不做** |
| cc-switch 本地统计 | `usage_daily_rollups` 表 | ⚠️ 数据停留在 2026-08-14，不可用 |
| cc-switch 本地统计 | `proxy_request_logs` 表 | ⚠️ 记录较新（session 日志同步），但全部挂在 `_session` 占位 provider 下，**无法归属到具体 key**；可按 model 名（kimi-*/deepseek-*）聚合出"平台级"消耗 |

**结论**：key 列表与密钥统一从 `~/.cc-switch/cc-switch.db` 只读读取（阿泽已有维护习惯，单一事实来源）；DeepSeek 能查实时余额；Kimi 只能查账号信息。

## 3. 调整说明（相对之前讨论）

阿泽选的"Kimi = 账号信息 + 消耗统计"，实测后消耗统计**无法按 key 拆分**（数据不存在）。调整为：

- Kimi 卡片：账号信息（昵称 / 等级 / user_id 尾号）+ "额度接口不可用"标注
- 窗口底部加一行平台级汇总：今日 / 本周 tokens（按 model 前缀聚合自 `proxy_request_logs`，标注"按平台合计，无法按 key 拆分"）

## 4. 功能范围（v1）

- **F1 悬浮窗主体**：tkinter，always-on-top，可拖动，深色卡片风，尺寸小巧
- **F2 卡片（按 key 去重）**：
  - DeepSeek（2 个配置共用 1 把 key → 1 张卡，标注"2 个配置共用"）：余额 ¥xx.xx；低于阈值变色（默认 <¥5 橙色，接口异常红色，可在配置文件改）
  - Kimi ×3（3 把不同账号的 key）：名称、昵称、等级、user_id 尾号、"额度不可查"灰字
  - 当前使用中的 key 高亮角标（读 `settings.json` 的 `currentProviderClaude`）
- **F3 底部汇总行**：今日 / 本周 tokens 消耗（平台级，来源 `proxy_request_logs`，unix 秒时间戳）
- **F4 刷新**：手动刷新按钮 + 自动刷新（默认 300s，可配）；HTTP 走 `http://127.0.0.1:7890` 代理（可配）；网络请求放子线程，UI 不卡
- **F5 窗口位置记忆**：关闭再开恢复上次位置（存 `%LOCALAPPDATA%\key-usage-widget\config.json`）
- **F6 密钥安全**：密钥只从 cc-switch.db 内存读取，不落任何新文件、不回显

### v1 不做（需要时再开 v2）

系统托盘、exe 打包（PyInstaller，需另行批准安装与打包命令）、Claude OAuth 五小时/七天、按 key 消耗拆分、历史曲线图

## 5. 界面草图

```
┌─ Key 用量面板          ⟳ ─┐
│ ● Kimi-大号  ⌈当前使用⌉    │
│   昵称: Allegro 会员       │
│   额度: 官方接口不可用      │
│ ● Kimi-二号               │
│   昵称: Allegretto 会员    │
│   额度: 官方接口不可用      │
│ ● DeepSeek（2 个配置共用）  │
│   余额: ¥6.25             │
├───────────────────────────┤
│ 今日 1.2M tok │ 本周 9.8M  │  ← 平台合计，无法按 key 拆分
└────────── 更新于 14:32 ────┘
```

## 6. 技术方案

- Python 3.11（本机已装），**零第三方依赖**，纯标准库：tkinter / urllib / sqlite3 / json / threading
- DB 只读打开：`sqlite3.connect("file:...?mode=ro", uri=True)`
- 网络：urllib + ProxyHandler，超时 10s
- 项目结构：

```
D:\Mings_Project\key-usage-widget\
  PRD.md
  app.pyw            # 入口（双击运行，无控制台）
  keymon\
    __init__.py
    config.py        # 路径、代理、刷新间隔、阈值等常量 + 用户配置读写
    ccdb.py          # cc-switch.db 读取：key 去重、当前 key、平台消耗聚合
    quota.py         # DeepSeek balance / Kimi me 查询（子线程、超时、缓存）
    ui.py            # 悬浮窗与卡片
  README.md          # 使用说明
```

- git：项目文件夹独立 `git init`，开发分支 `feature/key-usage-widget`（本会话所有提交都落此分支；推送远程前需阿泽批准）

## 7. 里程碑 checklist（对应提交粒度）

> 规则：一项完成 → 勾选 → 更新进度 → 一次本地提交。

- [x] M1 项目骨架：`git init` + 分支 `feature/key-usage-widget` + 目录结构 + `config.py`
- [x] M2 `ccdb.py`：key 去重读取、当前 key 判定、平台消耗聚合（附自测输出验证）
- [x] M3 `quota.py`：DeepSeek 余额 + Kimi 账号信息查询，子线程并发、超时、异常处理（附自测输出验证）
- [x] M4 `ui.py` + `app.pyw`：悬浮窗、卡片、手动刷新、底部汇总行
- [x] M5 体验完善：自动刷新、低余额/异常变色、当前 key 角标、窗口位置记忆
- [x] M6 README + 整体验收（阿泽双击试用，对照第 8 节验收标准）

## 8. 验收标准

1. 双击 `app.pyw` 出窗，置顶、可拖动、无控制台黑框
2. DeepSeek 余额数值与 platform.deepseek.com 控制台一致
3. Kimi 三卡昵称/等级正确，与各自 kimi.com 账号一致
4. 当前使用的 key 有角标，切换 provider 后（重启面板）跟随变化
5. 点刷新不卡 UI（网络在子线程）；拔代理后卡片显示异常红字而不是卡死
6. 关闭再开，窗口位置保留
