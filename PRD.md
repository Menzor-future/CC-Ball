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

---

# v2 改造：极简半透明用量表

## v2-1 目标

响应阿泽需求：背景半透明、布局更紧凑、每个 provider 配置一行，只显示 **商名 | 选中模型 | 5h 余量 | 7day 余量**。

## v2-2 关键限制

- **Claude Official**：5h/7day 来自 Anthropic 未公开端点 `https://api.anthropic.com/api/oauth/usage`，需要 Claude Code 登录后的 OAuth token。
- **Kimi For Coding**：实测可通过 `GET https://api.kimi.com/coding/v1/usages` 拿到 `usages.limit_5h.used_ratio` 与 `usages.limit_7d.used_ratio`，剩余量 = `1 - used_ratio`。
- **DeepSeek**：没有官方 5h/7day 接口，只有 `/user/balance` 余额；DeepSeek 行在 5h/7day 两列位置合并显示「余额 ¥x.xx」，不再显示 N/A。
- 本机当前未检测到 Claude Code 登录态，Claude Official 行会显示 `N/A`；代码预留，登录后自动生效。

## v2-3 数据方案

| 列 | 来源 | 说明 |
|---|---|---|
| 商名 | `providers.name` | 每个 provider 配置一行 |
| 选中模型 | `settings_config.env.ANTHROPIC_DEFAULT_FABLE_MODEL`，不存在则依次 fallback 到 `*_HAiku_MODEL`、`*_OPUS_MODEL` | 代表该配置当前默认调用的模型 |
| 5h 余量 | Kimi：`/v1/usages` 的 `usages.limit_5h.used_ratio`<br>Claude Official：`/api/oauth/usage` 的 rolling 5h 条目<br>DeepSeek：合并到「余额」列显示 | 显示为剩余百分比 |
| 7day 余量 | Kimi：`/v1/usages` 的 `usages.limit_7d.used_ratio`<br>Claude Official：`/api/oauth/usage` 的 weekly 条目<br>DeepSeek：合并到「余额」列显示 | 显示为剩余百分比 |

- OAuth token 获取顺序：
  1. `~/.claude/.credentials.json`（如未来存在）
  2. Windows Credential Manager 中尝试读取 `Claude Code` / `anthropic` 相关条目（如未来存在）
  3. 都不存在则显示 `N/A`

## v2-4 界面草图

```
┌─ Key 用量面板          ⟳ ✕─┐
│ 账号名    模型         5h         7day       │
│ Kimi-1   k2.7-code    99%(3h)   70%(1d)     │
│ Kimi-2   k3[1M]       85%(2h)   45%(5d)     │
│ DeepSeek v4-pro       余额 ¥6.25            │
│ DeepSeek v4-flash     余额 ¥6.25            │
│ Claude   ...           N/A        N/A        │
└──── 更新于 14:32 ─────────────────────────────┘
```

- 背景效果：Windows Acrylic / Mica 磨砂玻璃（文字 100% 不透明，背景模糊透明）
- 窗口尺寸：约 `540x160` 起，根据行数自适应宽度/高度
- 当前使用的 provider 行**文字加粗** + 背景高亮
- 自动刷新：每分钟刷新一次（`REFRESH_INTERVAL_S = 60`）
- 表头可点击列排序（至少支持按账号名排序）

## v2-5 技术变更点

- `ccdb.py`：新增 `read_providers()` 返回每个 provider 配置（不再按 key 去重）；新增 `get_default_model()`
- `quota.py`：新增 `query_kimi_usages(token)` 解析 5h/7day；新增 `query_claude_usage(oauth_token)` 作为 Claude Official 预留
- `ui.py`：重写为表格布局；调用 Windows DWM API 实现 Acrylic/Mica 磨砂玻璃背景；在 5h/7day 百分比后括号显示 `reset_time` 剩余时间；表头「商名」改为「账号名」；Kimi 行显示账号昵称，DeepSeek/Claude 显示品牌名
- `quota.py`：Kimi 查询同时并发获取 `/v1/me` 账号昵称，写入结果 `account_name`
- `config.py`：`REFRESH_INTERVAL_S` 改为 `60`；`WINDOW_ALPHA` 保留作为 DWM 不可用时 fallback
- `README.md` 与 `PRD.md` 同步更新

# v3 改造：圆球仪表盘 + 展开动画

## v3-1 目标

响应阿泽需求：默认只显示一个圆形仪表盘，展示当前选中配置的 5h 已用量百分比；点击圆球后通过动画展开完整方形列表；去掉标题栏，消除窗口空白。

## v3-2 界面与交互

- **默认状态**：120×120 小圆球窗口。
  - 灰色底环 + 彩色进度弧线（已用量 <50% 绿、50%-80% 橙、≥80% 红）。
  - 中心显示已用量整数百分比，如 `60%`。
  - DeepSeek/Claude 等无 5h 数据时显示 `N/A`。
- **点击圆球**：
  1. 圆球文字渐隐。
  2. 透黑圆形从中心扩张并填满方形窗口。
  3. 方形列表文字渐显。
- **展开状态**：去掉标题栏的紧凑表格，底部 footer 左侧 ⟳ 刷新、右侧 ✕ 收起。
- **点击 ✕**：直接切回圆球。

## v3-3 技术变更点

- `ui.py`：
  - 新增 `_OrbView`（Canvas 圆球）与 `_TableView`（表格）。
  - 新增 `anim_canvas` 作为过渡动画层，使用 Canvas `create_oval` 实现圆形扩张。
  - 新增 `_lerp_color` 颜色插值，实现文字渐隐/渐显。
  - `UsageWidget` 维护 `_mode`（`orb` / `table`），切换时保留窗口中心位置。
  - 移除顶部标题栏，将 ⟳ / ✕ 移入表格 footer。
  - 精确计算表格宽高，消除右侧/下方空白。
- `config.py`：
  - `DEFAULT_USER_CONFIG` 增加 `"mode": "orb"`，记忆上次展开/收起状态。
- `README.md` 与 `PRD.md` 同步更新。

## v3-4 里程碑 checklist

- [x] V3-M1 圆球仪表盘：Canvas 绘制圆环 + 百分比，显示当前配置 5h 已用量，低量变色。
- [x] V3-M2 展开/收起动画：点击圆球文字渐隐、圆形扩张为透黑方形、列表文字渐显；✕ 收起回圆球。
- [x] V3-M3 去标题栏 + 空白优化：去掉“Key 用量面板”标题，精确几何消除右侧/下方空白。
- [x] V3-M4 文档与验收：PRD/README 更新，阿泽验收。

> 注：V3 实际实现已从 tkinter 改为 PySide6（`keymon/ui_qt.py`，阿泽要求用成熟 UI 库），V4 基于 PySide6 版本。

# v4 改造：展开/收起动画重排（三阶段时序）

## v4-1 目标

响应阿泽需求：重新编排展开/收起动画为清晰的三阶段时序，彩环旋转回缩独立成段，背景渐隐渐显并入变形过程。

## v4-2 展开时序（点击圆球）

1. **阶段2（220ms）**：彩环终点固定、起点绕环旋转回缩到 0 长度（OutCubic 减速曲线，像被"卷走"）；百分比数字 + 深灰底环同时间段线性淡出。球背景全程保持 100% 不透明 → 结束时只剩透黑色圆球。
2. **阶段3（280ms）**：透黑球 morph 变形成方形，同时球背景 dip：随 morph 进度按 `sin(π·morph)` 曲线 1.0→0.25→1.0（变形中段最虚，不是完全不可见）；表格文字全程 0→100% 渐显。
3. **变形完成瞬间，文字恰好 100% 可见**（两动画同起同止）。

## v4-3 收起时序（点击 ✕ / 失焦）

完全对称倒放：

1. 表格文字渐隐 + 方形 morph 收缩回圆球，球背景 dip 同展开（1.0→0.25→1.0）。
2. 完成后：深灰底环 + 数字渐显；彩环从 0 长度旋转增长回当前进度（220ms 减速反向）。

## v4-4 技术变更点（`keymon/ui_qt.py`）

- 新增 `_arc_t` Qt 属性（1→0 弧长系数）驱动彩环旋转回缩；彩环起点角度 = 终点角度 + 弧长，morph 阶段弧长恒为 0。
- 轨道环 + 数字的可见性独立为 `_fade`（阶段2 淡出/淡入），不再与表格渐显共用。
- 删除 `_bg_out` / `_bg_in` 独立背景动画：背景 dip 改由 `_set_morph` 内按 `1.0 - 0.75·sin(π·morph)` 计算，与变形天然同步。
- 动画结构：`Sequential[ Parallel(arc_t, orb_fade) 220ms → Parallel(morph, table_fade) 280ms ]`，收起反向。
- 圆球元素（环/弧/文字）半径固定为原始大小，不随变形放大。

## v4-5 里程碑 checklist

- [x] V4-M1 阶段2 独立化：新增 `_arc_t` 彩环旋转回缩（OutCubic 220ms），数字+底环同步淡出，球背景全程不透明。
- [x] V4-M2 阶段3 合并：背景 dip 挂到 morph 进度（sin 曲线），删除独立 bg 动画，morph+表格渐显并行 280ms。
- [x] V4-M3 收起对称倒放：文字渐隐+收缩 dip → 底环/数字渐显 + 彩环旋转增长回当前进度。
- [x] V4-M4 验收：阿泽实测展开/收起流畅度与视觉效果。
- [x] V4-M5 修复"变形期间宽度偶尔被影响"：refresh() 原先在 UI 线程 join 网络子线程，
      网络变慢时事件循环被冻结、动画卡顿跳变。改为全异步（worker 线程 + 信号回主线程 +
      重入守卫），表格预热移至首次数据到达时；另加 _expand/_collapse 目标态硬守卫防退化动画。

# v5 改造：代理自动探测与回退（无代理场景兼容）

## v5-1 背景

2026-09-17 阿泽反馈：昨天正常，今天打开全部显示 `N/A`。排查结论：`config.py` 写死
`PROXY_URL = http://127.0.0.1:7890`，而当天 Clash 未启动，所有请求 `WinError 10061`
连接被拒 → `h5_remaining` 取不到 → 圆球 N/A。小部件不能假设代理永远在线。

## v5-2 目标

**直连优先**（Kimi/DeepSeek 均为国内服务，无需代理）；直连失败才尝试代理；
两者都不行才报错。全过程无需用户改配置、无感切换，并保留可诊断性（日志可见
当前走的是直连还是代理）。

## v5-3 方案

- `quota.py`：
  - 废弃 import 时构建一次的全局 `_opener`，改为按请求现场构建（直连 opener /
    代理 opener 两个轻量对象，缓存复用）。
  - 模块级 `_preferred`（`"direct"` / `"proxy"`），**初值 `"direct"`**（阿泽指定优先直连）；
    某模式请求成功后记住该模式，**本批次剩余请求与下一批次优先沿用**，避免每批次
    都先白失败一次。多 worker 线程并发，读写加锁。
  - `_request` 增加一次回退重试：首选模式失败且错误是**传输层错误**（`URLError`：
    连接被拒/超时/DNS 失败）→ 切另一模式重试一次；**`HTTPError`（4xx/5xx）不回退**
    ——那是鉴权/服务端问题，换代理无意义。
  - 两模式都失败 → 返回原错误；回退成功 → 在 `ui.log` 记一条模式切换日志
    （provider、两模式错误摘要），不逐请求记，避免刷屏。
- `config.py`：`PROXY_URL` 语义改为"直连失败时的备用代理"，注释同步更新。
- UI 层零改动：N/A 仅在数据真拿不到时出现，不再因代理未开误报。

## v5-4 里程碑 checklist

- [x] V5-M1 `quota.py` 直连优先 + 传输层失败代理回退 + 成功模式记忆 + 切换日志
- [x] V5-M2 实测验证：① 当前无代理环境（正好复现故障现场）`python -m keymon.quota`
      全部 provider 返回真实数据（走直连，elapsed ~700ms）；② 合成测试 4 条全过——
      传输层失败触发回退、HTTPError 不回退、双失败抛末次错误、直连成功不碰代理
- [x] V5-M3 README/PRD 同步 + 本地提交

# v6 改造：圆球悬停关闭小球 + 退出确认弹窗

## v6-1 背景

2026-09-17 阿泽需求：鼠标悬停圆球时，右上角浮出一个同设计语言的小圆关闭按钮，
点击后弹窗确认关闭。顺带发现：**软件目前没有任何界面退出入口**（表格 footer 的 ✕
只是收起回圆球），本需求是第一个真正的退出路径。

## v6-2 方案

- **关闭小球**（`keymon/ui_qt.py`）：
  - orb 模式悬停窗口时浮出：直径约 24px 圆形实底钮，压住圆球右上角轮廓
    （窗口角部透明，视觉上探出球沿）；深灰底 `BG` + 细边 `GRID`，白色 ✕；
    hover 变红（关闭语义色，同低余额红 `RED`）。
  - 淡入 150ms / 淡出 200ms（OutCubic，与 V4 动画曲线一致）；移出时延迟 200ms
    再隐藏，给"球 → 按钮"的鼠标移动留缓冲，防止按钮闪烁（标准 hover 桥接）。
  - 仅在 orb 模式出现；变形动画进行中不响应点击。
  - 位置约束说明：球体之外即窗口之外，窗外无法绘制，故按钮压球沿呈现，
    非"完全脱离球体的悬浮"。
- **确认弹窗**：深色定制 `QMessageBox`（背景 `BG`、文字 `TEXT`、按钮同配色），
  置顶（跟随主窗口 always-on-top），按钮「确认关闭」（红）/「取消」（默认聚焦），
  Esc = 取消；确认后 `_save_state()` 并退出应用。
- 表格 footer 的 ✕ 语义不变（收起）。

## v6-3 里程碑 checklist

- [x] V6-M1 悬停关闭小球：orb 模式悬停浮出/移出延迟隐藏、同设计语言配色、hover 变红
- [x] V6-M2 退出确认弹窗：深色定制 QMessageBox 置顶，默认取消，确认后保存状态退出
- [x] V6-M3 实测：离屏自测 7 项全过（初始隐藏/淡入/桥接/淡出隐藏/弹窗默认取消/展开撤掉/
      动画期守卫）+ 真实启动 ui.log 无异常；README/PRD 同步 + 本地提交

## v6-4 验收反馈调整（2026-09-17 阿泽实测）

- 关闭小球最终位置移至窗口物理最右上角 `(76,0)`（球外即窗外，此为离球最远合法位）。
- 出现/消失改为位移动画：从圆球右上沿 45° 处的 6px 小点，沿对角线飞出至右上角并
  长大为 24px 按钮（260ms OutCubic）；消失为反向缩小回收（200ms）；透明度随进度快速 ramp。
- 说明：小球是子控件，永远在父绘制之上，"从球背后"以"起点贴球沿 + 初始小点"近似。

- [x] V6-M4 位移动画替换纯淡入淡出 + 终点移至窗角

## v6-5 验收反馈调整（2026-09-17 阿泽二次实测）

- 动画再放慢：弹出 260→450ms，收回 200→350ms。
- 进一步远离圆球：子控件被限制在 100×100 主窗口内（窗外无法绘制），(76,0) 已是用尽窗口的极限。
  改为**跟随主窗口的独立小窗**（Qt.Tool 无边框、不进任务栏、WA_ShowWithoutActivating 不抢焦点、
  随主窗移动/置顶），终点悬浮于圆球斜上方约 20px 处（父坐标 (102,-20)，与主窗零重叠）。

- [x] V6-M5 动画减速至 450/350ms + 关闭小球改为独立跟随小窗悬浮出窗外

## v6-6 验收反馈调整（2026-09-17 阿泽三次实测）

- 卫星位 (102,-20)（球心距 86px）过飘，"飞出去了很奇怪"。
- 终点回调至与圆球**相切的徽章位** (82,-6)（球心距 ~62px）：不压进度环（解太靠近）、
  不悬空（解飞出去），像别在球肩上的小徽章；飞行距离 33→21px。

- [x] V6-M6 终点回调至相切徽章位 (82,-6)

## v6-7 验收反馈修复（2026-09-17 阿泽四次实测）

- 阿泽反馈"还是有距离很远、没有跟随圆球"：根因是 `Qt.Tool` 独立小窗**不会自动跟随
  主窗移动**——拖动圆球时按钮留在原地，越拖越远。
- 修复：MainWindow.moveEvent 里手动吸附（按钮可见且弹出动画非运行中时，snap 到徽章位）；
  变形动画的 setGeometry 同样触发 moveEvent，一并覆盖。

- [x] V6-M7 关闭小球手动跟随主窗（moveEvent 吸附同步）

## v6-8 验收反馈调整（2026-09-17 阿泽五次实测）

- 轨迹明确锚定圆心放射线：起点=球面（距圆心 50px），沿 45° 径向外飞 ~30px，
  终点距圆心 80px（父坐标 (95,-19)）；全程直线，行程 ~31px。

- [x] V6-M8 轨迹改为圆心放射线：起点球面、终点球心距 80px

## v6-9 验收反馈修复（2026-09-17 阿泽六次实测）

- 阿泽反馈"关闭按钮出现的位置离球很远"（改 4 次坐标都没用）：根因是坐标系错位——
  `CloseOrbButton` 是 `Qt.Tool` **独立顶层的窗口**，`setGeometry/move` 用的是**屏幕全局坐标**；
  而 `_close_dot_rect/_close_full_rect` 是**父窗口内坐标**，直接被当成全局坐标写入了。
  结果按钮永远出现在屏幕左上角 (95,-19) 附近，与圆球位置无关（之前"飞出去/不跟随"同源）。
  离屏测试未抓到是因为断言只比对 geometry 数值（恒等于被写入的常量），从未断言过
  屏幕全局位置与父窗 mapToGlobal 的关系。
- 修复：所有关闭小球几何操作统一走坐标换算（父内坐标 ↔ 全局坐标只在 set/get 两处转换），
  动画帧、moveEvent 吸附、复位、完成态判断全部修正；离屏测试改为一律用
  `_btn_parent_rect()`（换算回父内坐标）断言，并新增全局位置/拖动跟随断言。

- [x] V6-M9 关闭小球坐标系修正：父内坐标与屏幕全局坐标显式换算

## v6-10 验收反馈微调（2026-09-17 阿泽七次实测）

- 坐标系修正后首次看到真实位置：终点距圆心 80px 略远，收到 70px
  （父坐标 (88,-12)，与球肩缝隙 ~9px）；起点小点仍在球面（50px），行程 ~21px。

- [x] V6-M10 关闭小球终点内收至圆心距 70px (88,-12)

## v6-11 验收反馈修复（2026-09-17 阿泽八次实测）

- 阿泽反馈"回去的动画异常：按钮先回去、又弹出来、然后消失"——收回动画被重启了两次。
  根因：收回途中按钮从光标底下"抽走"，光标未动但底下窗口从按钮小窗变成主窗，Qt 给主窗
  合成假的 `Enter` 事件 → `enterEvent` 误判用户返回，收回中途重启为弹出；同时按钮 `Leave`
  重启的 200ms 倒计时到点又触发一次收回 → "回去→弹出→消失"。
- 修复（动画状态机收口）：
  1. `_start_close_pop_in`：任何弹出/收回动画运行中直接 return，不收 Enter 改向；
  2. `_start_close_pop_out`：收回运行中不重启（弹出运行中仍允许倒计时翻转为收回）；
  3. eventFilter 按钮 `Enter`（恒为真实 hover，几何缩小不会产生假 Enter）：收回途中
     立即改向弹出——真实返回按钮仍可用。
- 离屏新增 PASS 10（合成 Enter 不打断收回）/ PASS 11（真实 hover 反向弹出）回归锁定。

- [x] V6-M11 收回动画防重入：合成 Enter 不改向，真实 hover 改向，倒计时不重触发

# v7 改造：任务栏隐藏 + 系统托盘 + 开机自启

## v7-1 背景

阿泽需求（2026-09-17）：

1. 默认**任务栏不显示** python 这项应用（目前主窗在任务栏有按钮）。
2. 仅在右下角系统托盘显示图标。
3. 托盘**右键菜单支持退出**。
4. 支持**是否开机自启**的配置（勾选切换）。

## v7-2 方案

- **任务栏隐藏**（`keymon/ui_qt.py`）：主窗 `MainWindow.setWindowFlags` 增加 `Qt.Tool`
  （项目内已有先例：关闭小球即 Qt.Tool，天然不进任务栏、不抢焦点）。
  副作用接受：Alt+Tab 列表不再出现面板（对本悬浮件属预期）；置顶/拖动/动画行为不变。
- **系统托盘**：`QSystemTrayIcon` + 程序化生成的圆点图标（QPixmap 画圆，配色同面板），
  tooltip「Key 用量面板」。托盘可用性兜底：极少数环境托盘不可用时降级为只保留原行为，
  并在 ui.log 记一行警告，不影响主功能。
- **右键菜单**（`QMenu`，深色调试图配色）：
  - 「显示 / 隐藏面板」——切换主窗可见性；
  - 「开机自启」——checkable，勾选状态即注册表实际状态；
  - 「退出」——复用现有退出确认弹窗（V6-M2），确认后保存状态退出。
  - 左键单击托盘图标：等同「显示 / 隐藏面板」。
- **开机自启**（新模块 `keymon/autostart.py`）：
  - 写 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\key-usage-widget`，
    值为 `"<pythonw.exe>" "<app.pyw 绝对路径>"`；取消自启即删该值。
  - pythonw 定位：`sys.executable`，若 basename 是 `python.exe` 则同目录换成 `pythonw.exe`
    （无控制台黑框）；预留 `sys.frozen` 分支兼容未来 exe 打包。
  - 注册表是单一事实来源，托盘勾选状态实时读注册表，启动时不同步写配置。

## v7-3 里程碑 checklist

- [x] V7-M1 主窗加 `Qt.Tool` 隐藏任务栏按钮 + 离屏断言（flags 含 Tool、任务栏无关几何不变）
- [x] V7-M2 托盘图标 + 右键菜单（显示/隐藏、开机自启勾选、退出复用确认弹窗）+ 左键切换可见性
- [x] V7-M3 `autostart.py`：HKCU Run 读写、pythonw 定位、托盘勾选与注册表同步、不可用兜底
- [x] V7-M4 实测（离屏 18 项全过：flags/菜单结构/显隐切换/注册表读写与恢复/托盘联动；真实启动 ui.log 无异常）+ README/PRD 同步 + 本地提交

# v8 修复：关闭小球收回完成后"闪出又消失"（合成 Enter 时序回归）

## v8-1 现象与根因

阿泽实测（v7 上线后）：关闭按钮返回圆球的动画仍会"先回到圆球、然后快速闪出来又消失"。
V6-M11 曾修过同款症状，v7 主窗改 `Qt.Tool` 后复发。

离屏复现（`tests/offscreen_v8_closebtn.py` PASS D）锁定根因：收回途中按钮从光标下抽走，
Qt 补发的合成 Enter 在 v6 时序下排在动画帧之前到达（被"运行中"守卫拦下）；主窗改
`Qt.Tool` 后事件投递时序变化，该 Enter 排在了 `finished`（hide+复位）**之后**——到达时
动画已结束，守卫失效 → 误判 hover 重启弹出；用户继续移开鼠标 → 200ms 倒计时 → 再次收回。
主观即"回到圆球 → 闪出来 → 消失"。

## v8-2 修复方案（`keymon/ui_qt.py`）

- **dismissal 位置记录**：`_on_close_pop_done`（收回完成）记录 `QCursor.pos()` 到
  `_close_suppress_pos`；`_start_close_pop_in` 里光标位置未变时的 Enter 一律视为
  合成事件，直接忽略（不再依赖"动画运行中"这一时序巧合）。
- **真实移动解除抑制**：主窗开 `mouseTracking`，`mouseMoveEvent` 里光标一有真实移动
  即清除抑制并按真实 hover 重新判定弹出——合成 Enter 被吞的场景由"光标在窗内移动"
  兜底，行为比纯 Enter 驱动更稳。
- 真实 hover 按钮（eventFilter Enter）天然伴随移动，同步清除抑制；V6-M11 的
  运行中守卫、hover 桥接、倒计时防抖全部保留。

## v8-3 里程碑 checklist

- [x] V8-M1 离屏复现锁定根因（PASS D 修复前稳定 FAIL：收回完成后合成 Enter 误弹出）
- [x] V8-M2 修复：dismissal 位置抑制 + mouseTracking 真实移动兜底，
      V6-M11 回归（运行中不改向/真实 hover 改向）不破坏，离屏 7 项全过 + v7 回归 18 项全过
- [x] V8-M3 真实启动 ui.log 无异常 + README/PRD 同步 + 本地提交

# v9 改造：打包为可安装/卸载的 Windows 应用

## v9-1 背景

阿泽需求（2026-09-17）：把项目做成"正经应用"——可安装、可在「设置→应用」里卸载。
选定路线 A：PyInstaller 打包 exe + Inno Setup 做安装向导（阿泽拍板）。

## v9-2 方案

- **PyInstaller**：`--onefile --windowed --name key-usage-widget` → `dist\key-usage-widget.exe`。
  `autostart.py` 的 `sys.frozen` 分支接管（开机自启直接指向 exe 自身，不再依赖 pythonw+脚本）。
- **Inno Setup**（`installer.iss`）：
  - 用户级安装（免管理员）：`%LOCALAPPDATA%\Programs\key-usage-widget\`；
  - 开始菜单快捷方式；桌面快捷方式作为可选项（默认不勾）；
  - 注册到「设置→应用」（Uninstall 注册表项：图标/版本/发布者/卸载命令）；
  - 安装向导任务页提供「开机自启」勾选，**默认不勾**；与托盘勾选写同一个
    HKCU Run 项（`autostart.py` 单一事实来源不变，两处天然同步）；
  - 卸载：删安装目录 + 删 HKCU Run 项 + 询问是否删除 `%LOCALAPPDATA%\key-usage-widget` 配置目录。
- **版本号**：`config.py` 新增 `APP_VERSION`，Inno 脚本与 README 引用同一版本。

## v9-3 里程碑 checklist

- [x] V9-M1 工具链就绪：`pip install pyinstaller`（6.22.3）+ Inno Setup 6.7.3（winget，用户级安装于 `%LOCALAPPDATA%\Programs\Inno Setup 6`）
- [x] V9-M2 PyInstaller 打包：`key-usage-widget.exe` 46.3MB（onefile+windowed），双击实测悬浮窗/托盘/表格预热全部正常；frozen 分支自启命令指向 exe（验证通过）
- [x] V9-M3 `installer.iss`：用户级安装（`PrivilegesRequired=lowest` + `PrivilegesRequiredOverridesAllowed=commandline` 保静默也走用户级）、开始菜单快捷方式、自启勾选（默认不勾，与托盘同一 Run 项）、注册卸载项（AppId GUID + UninstallDisplayIcon）、卸载清理安装目录+Run 项+交互询问删配置
- [x] V9-M4 实测静默安装→运行→静默卸载全流程（安装目录/自启注册表/卸载条目全部验证；应用运行 ui.log 正常、任务栏无入口；卸载后无残留、配置目录保留）+ README/PRD 同步 + 本地提交
- 踩坑记录：① Git Bash 会把 `/VERYSILENT` 等 Inno 参数按 Unix 路径规则转译成 `C:/Program Files/Git/...`，静默安装必须用 PowerShell 调；② `PrivilegesRequiredOverridesAllowed=dialog` 静默模式也弹"安装模式选择"对话框导致卡死，改 `commandline`；③ 应用名含 CJK 且无中文语言包时向导页标题 ANSI 乱码，`[Messages]` 段覆盖为英文；④ Inno 官方版不内置简体中文语言包，任务描述写中英双语。

# v10 改造：圆球语义统一为"剩余量"

## v10-1 背景

2026-09-18 阿泽反馈"代理一没开软件就歇菜了，圆球显示 0% 点开又显示 100%，以为是满了"。
排查结论：**网络层完全正常**（代理关闭状态下 5 个 provider 全部直连成功，V5 直连优先
逻辑工作正常）。真实问题是**语义分裂**：V3 定圆球显示"已用量"（越满越危险），V2 定
表格显示"剩余量"（越满越安心）——同一时刻圆球 0%（已用）与表格 99%（剩余）指向同一
状态，阿泽第一次见被误导以为额度满了。

## v10-2 方案（阿泽拍板：全部统一为剩余量）

- `ui_qt.py::_orb_value`：圆球直接显示 `h5_remaining` 剩余百分比（不再 `1 - remaining`）；
  弧长绘制逻辑不变——语义从"已用弧长"自然变为"剩余弧长"：**弧满=剩得多=绿色安心，
  弧近空=快用完=红色告急**（电量直觉）。
- `_used_color` → `_remaining_color`：按剩余量配色，阈值与表格 `_pct_color` 对齐
  （剩 <20% 红、<50% 橙、其余绿）。
- 离屏测试新增语义断言：剩余 99% → 显示 `99%` 绿色；剩余 5% → 显示 `5%` 红色。

## v10-3 里程碑 checklist

- [x] V10-M1 现象排查：代理关闭实测数据层全部直连成功（排除网络回归），锁定语义分裂根因
- [x] V10-M2 圆球改剩余量语义 + 配色阈值与表格对齐 + 离屏语义断言（99%绿/5%红），
      v7/v8 回归全过（v8 时序抖动需单独跑，连跑 3 次稳定）
- [x] V10-M3 重新打包 exe 并热替换安装目录，实测运行正常 + README/PRD 同步 + 本地提交

# v11 改造：macOS 移植（给朋友用）

## v11-1 背景

阿泽需求（2026-09-18）：打 Mac 版给朋友用。硬约束：PyInstaller 不可交叉编译，
mac 包必须在 macOS 环境产出；现有代码多处 Windows-only（winreg/路径/字体/托盘行为）。

## v11-2 方案

- **打包环境**（待阿泽选定）：A 借 Mac 本机打包 / B GitHub Actions macOS runner 云打包 /
  C 朋友自助跑源码。
- **平台抽象**（`sys.platform` 分支）：
  - `autostart.py`：win32 走注册表（现状），darwin 走 LaunchAgents
    （`~/Library/LaunchAgents/com.key-usage-widget.plist`，RunAtLoad=true）；
  - `config.py`：配置/日志目录改 `platformdirs`（Win: `%LOCALAPPDATA%`，
    mac: `~/Library/Application Support/`）；cc-switch 路径保持 `~/.cc-switch`（跨平台约定）；
  - `ui_qt.py`：字体 mac 用 `PingFang SC`；托盘行为按 mac 菜单栏习惯微调；
  - 数据层（ccdb/quota）天然平台无关，零改动。
- **分发**：`.app` 打 `.dmg`（或 zip）；未签名需"右键→打开"绕过 Gatekeeper，
  README 写清楚（朋友场景不买 $99/年开发者账号）。

## v11-3 里程碑 checklist

- [x] V11-M1 阿泽选定打包环境（A/B/C），B 则建好 GitHub workflow
      （2026-09-18：阿泽选 B；`.github/workflows/build-mac.yml` macos-13/14 双架构 matrix，
      产出 .app + dmg artifact，LSUIElement 隐藏 Dock 图标，push main 自动触发 + 手动触发。
      已推送 git@github.com:Menzor-future/CC-Ball.git：main=全项目压缩单提交（orphan），
      feature/key-usage-widget=完整 52 提交历史；本机 SSH 公钥已添加到 GitHub 账号）
- [x] V11-M2 平台抽象改造：autostart/config/ui 三处分支 + Windows 回归（v7/v8/v10 全过）
      （2026-09-18 完成：config.py `_user_data_dir()` 免第三方依赖手写分支；autostart.py
      darwin 写 LaunchAgents plist；ui_qt.py 字体分支 PingFang SC；app.pyw boot 日志目录
      跟随 config；v7 18 项 / v8 7 项回归全过。ui.py 为 v3 起废弃的 tkinter 版，不移植）
- [ ] V11-M3 mac 侧打包产出 `.app`/`.dmg`，朋友实测：读他自己的 cc-switch、
      托盘/悬浮球/自启正常、Gatekeeper 绕过说明有效
- [ ] V11-M4 README（mac 安装说明）/PRD 同步 + 本地提交
