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
