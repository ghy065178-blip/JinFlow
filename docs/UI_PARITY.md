# 主界面与原可视化操控面板一致性对照

对照对象：旧脚本文件夹内的 `control_panel.html`（浏览器版可视化操控面板）。
桌面版 `src/jsj_desktop/ui/main_window.py` 已按同一套布局、文案、操作入口、
交互逻辑与功能行为重排，**两处功能完全相同**。

自动化回归：`tests/fixtures/panel_ui_spec.json` 保存原面板元素清单，
`tests/test_ui_parity.py` 静态校验全部文案、按钮、复选框、反馈提示、行为方法与
主题配色，并断言不再使用标签页 / 本地 HTTP 服务 / 浏览器。

## 1. 界面呈现

| 区域 | 原面板 | 桌面版 | 一致 |
|---|---|---|---|
| 配色 | `--bg:#0d1117` 等 GitHub 深色变量 | `ui/theme.py` 逐项复刻同一组 12 个 CSS 变量 | ✅ |
| header | 品牌 J 徽标 + h1「金数据报名 · 可视化控制平台」+ sub + 连接状态 pill + 北京时间 pill | 同结构、同文案（sub 追加「桌面版」标注） | ✅ |
| taskbar | 「多开任务」+ 任务标签（含独立 ↻）+ 新建/关闭/刷新 + hint | 同结构；每任务标签含主按钮、状态文字、独立 ↻ | ✅ |
| cards | 5 张卡：运行状态 / 距开放倒计时 / 提交尝试 / 服务器时钟偏差 / 最新反馈 | 同 5 张，字段与初始 note 一致 | ✅ |
| 左栏 | `.left-scroll` 内两个 panel：运行配置、报名信息 | 单页左栏可滚动容器 + 相同两个 panel（含 panel-h 的标题与右侧 tag） | ✅ |
| 右栏 | `.term` 实时终端：标题栏 + 日志 + 输入栏 | 同结构，日志配色 `#080b10` / `#c9d1d9` / 分级色一致 | ✅ |
| 提示 | 右下角 toast（3.2s） | 右下角浮动 toast（3.2s、左侧色条按 ok/err/warn） | ✅ |
| 表单信息 | info-grid 5 行 | 同 5 行；warnbox 按显示/隐藏切换 | ✅ |
| 布局宽度 | 左 400px 固定、右自适应 | 左 420px 固定、右自适应 | ✅ |

## 2. 操作入口（逐项对齐）

| 类别 | 入口 |
|---|---|
| header | 连接状态「实时监控已连接」、北京时间 |
| taskbar | `+ 新建任务`、`关闭当前`、`↻ 刷新状态`、每个任务标签的 `↻`、任务切换 |
| 运行配置 | 表单链接输入 + `读取表单`、`快速模式 --quick`、`仅演练 --dry-run`、`自动应答终端提问`、开放时间来源下拉（3 项）、手动时间、提前量/间隔/时长、`启动脚本`、`演练自检`、`停止` |
| 报名信息 | 档案下拉 select、`应用`、`更新`、`重命名`、`删除`、新档案名称 + `把当前信息存为新档案`、动态字段、`保存信息`、`重新载入` |
| 实时终端 | `脚本等待输入` 提示、`自动滚动`、`清空`、`导出日志`、`发送`、快捷按钮 `回车 / 1 / 2 / 3 / m / q` |

附加能力（**不占主界面**，通过菜单栏与弹窗提供，不影响两处呈现一致）：
「文件」菜单的旧版数据导入 / 档案导入导出 / 打开数据目录；「任务」菜单的
预览提交数据 / 重命名任务 / 停止全部；「帮助」菜单的设置与关于（含日志脱敏、
逐项确认、运行环境、合规说明）与隐私说明；预览提交数据弹窗。
1.2.0 起「帮助」菜单新增「检查更新与升级…」，对应独立弹窗
`ui/update_dialog.py`，并在「设置与关于」增加一个默认关闭的
「启动时自动检查新版本」复选框；这些附加能力仍不占主界面，
主界面的单页布局、全部文案、按钮、状态卡与配色逐项保持不变，
`tests/test_ui_parity.py` 全部断言继续通过。

## 3. 交互逻辑与功能行为

| 原面板行为 | 桌面版实现 | 一致 |
|---|---|---|
| `api()` 按 `task_id` 路由 | `TaskManager` 每任务独立上下文 | ✅ |
| SSE `state/log/tasks` 推送 | 线程安全 `queue.Queue` 事件 + `_poll` 100ms 消费 | ✅ |
| `renderState` 5 卡 + 按钮禁用 + waitPill | `_render_state`（含 `fmtCount` 格式：负数「已开放 X.Xs」，正数 `HH:MM:SS`） | ✅ |
| `appendLog` 分级着色、自动滚动、每任务日志缓存 | `_append_log` + `LogView`，每任务日志回放 | ✅ |
| `renderTaskTabs` 状态文字、8 个上限、主任务不可关闭 | `_render_task_tabs` + 按钮禁用条件 | ✅ |
| `refreshTask(tid)` 只刷新指定任务、不切换 | `_refresh_task(tid, is_tab)`（含 spinning 反馈） | ✅ |
| `saveUI/applyUI` 切换任务保留界面状态 | `_save_ui` / `_apply_ui` | ✅ |
| `initTask(replay)` 载入 state/config/log | `_init_task(replay)` | ✅ |
| `loadForm` 在线/离线切换 + warnbox | `_load_form` / `_handle_form_result` / `_show_warn` | ✅ |
| `evalBranch/contradictory/isVisible` 联动显隐 | 统一调用 `core.rules.is_visible`（与提交引擎同一实现） | ✅ |
| `renderFields` 单选 select / 文本 / 多选 + 可选项提示 | `_render_fields` + `_codes` + `_refresh_visibility` | ✅ |
| `fallbackFields` 离线纯文本字段 | `_render_fields` 离线分支 | ✅ |
| `collectValues` 只收可见字段 | `_collect_values` | ✅ |
| `saveConfig(silent)` 写配置并备份 | `_save_config` → `ConfigStore`（备份 + 原子替换） | ✅ |
| 档案 select `onchange` 立即应用 + 增删改 | `_on_profile_select` + `_apply_profile` / `_add_profile` / `_update_profile` / `_rename_profile` / `_delete_profile` | ✅ |
| `start(dry)` 先保存配置再启动 | `_start`（另外合并了「仅演练」复选框，见下） | ✅ |
| `send(text)` 与快捷按钮 | `_send_quick` / `_send_entry` | ✅ |
| `connect()` 连接状态指示 | header 常亮「实时监控已连接」（本地引擎，无 SSE 断线概念） | ✅ |
| 北京时间按服务端锚点走时 | 本机 `datetime.now(CST)`，每秒刷新 | ✅ |
| 导出日志文件名 `报名脚本运行日志.txt` | 同名默认文件名 | ✅ |

## 4. 有意的实现差异（不改变功能结果）

1. **深色单页取代浅色四标签页**：本次按用户要求把主界面改回与原面板一致的单页布局；
   「设置与关于」等附加信息移到「帮助」菜单弹窗，不再占用主界面。
2. **进程 → 独立线程**：原面板用子进程 + stdout 抓取 + 正则猜提示语；桌面版用
   独立线程 + 结构化 `InputProvider`。任务隔离改由独立配置目录与上下文保证，
   提交业务结果不变。状态卡的 `PID` 显示线程标识。
3. **自动应答**：原面板靠正则匹配终端提问后写 stdin；桌面版在缺项时直接弹窗或
   沿用配置值，不再解析 stdout，功能等价且更稳健。快捷按钮 `m`（逐项修改）
   对应设置弹窗中的「启动时逐项确认信息」。
4. **「仅演练」复选框**：原面板该复选框仅保存状态、不参与 `start()` 的 dry 判定；
   桌面版让勾选后点「启动脚本」也进入演练（避免无效控件），「演练自检」按钮行为不变。
5. **连接状态**：桌面版没有本地 HTTP 服务，故不存在「连接断开 / 重连」状态，
   pill 常亮显示「实时监控已连接」。
6. **文案微调**：notice 中「原脚本作为子进程被托管」等描述保留原措辞以对齐视觉，
   但实际运行机制已在 `docs/ARCHITECTURE.md` 说明；sub 追加「（桌面版）」标注。

## 5. 如何验证

```bash
python -m unittest tests.test_ui_parity -v     # 界面一致性静态回归
python -m unittest tests.test_update -v        # 1.2.0 检查更新与升级回归
python -m unittest discover -s tests -t . -v    # 全量 152 项（原 95 + 更新 57）
```
另可用 `PYTHONPATH=src python -m jsj_desktop` 打开窗口，与浏览器版面板逐项对照。
