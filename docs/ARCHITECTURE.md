# 架构与数据流

## 分层

```
┌──────────────────────────────────────────────────────────────┐
│ ui/（tkinter/ttk 原生窗口）                                    │
│   MainWindow：单页面板、任务标签、状态卡、日志视图、弹窗应答    │
│   ← 只通过 queue.Queue 接收引擎事件，不直接碰网络与业务数据      │
└───────────────┬──────────────────────────────────────────────┘
                │ 事件 (kind, task_id, payload) / 命令调用
┌───────────────▼──────────────────────────────────────────────┐
│ tasks/manager.py                                              │
│   最多 8 个 Task：独立 ConfigStore、独立统计/日志/表单结构      │
│   QueueSink（引擎事件入队）、GuiInputProvider（缺项弹窗应答）   │
└───────────────┬──────────────────────────────────────────────┘
                │ 后台线程 core.engine.run(ctx)
┌───────────────▼──────────────────────────────────────────────┐
│ core/（纯业务逻辑，无 GUI / 无 print / 无 input）               │
│   endpoint → rules → mapping → submit → engine                 │
│   与旧版 auto_submit.py 等价；由 legacy parity 测试背书         │
└───────────────┬──────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────┐
│ data/（用户数据目录，仅本机）                                  │
│   paths / config_store / profile_store / settings_store         │
└──────────────────────────────────────────────────────────────┘
```

## 一次运行的流程

1. 界面收集参数 → `TaskManager.start()` 建 `RunConfig`、`GuiInputProvider`、`QueueSink`、`stop_event`。
2. 后台线程执行 `core.engine.run(ctx)`：
   读取本任务 `报名信息.json` → 解析链接 → `Endpoint.fetch_form()` 拉取字段/规则/开放时间/验证码 → `config_to_chosen()` → `fill_form(only_missing=True)` 补缺 → `chosen_to_config()` 回写并备份 → `build_attributes()` 生成 `entryAttributes` → 演练则停止 → `calibrate_clock()` → 按时间来源等待 → 高频 `submit_once()` 冲刺 → `_finish()`。
3. 每一步通过 `EventSink` 发出 `log / state / form / preview / finished` 事件；Tk 主循环每 100 ms 消费队列并刷新控件。
4. 「停止」只置 `stop_event`；等待循环与冲刺循环在安全点退出，不杀进程。

## 关键设计取舍

| 决策 | 原因 |
|---|---|
| **tkinter/ttk** 而非 Qt/Electron/pywebview | 目标包含 Windows ARM64；Tk 随官方 CPython 分发，四个平台都无需第三方二进制轮子，运行时依赖为零 |
| **独立线程** 而非子进程 + stdout 抓取 | 旧版靠正则猜 `input()` 提示语应答，脆弱；改为结构化事件与显式 `InputProvider`，同时用独立配置目录保持任务隔离 |
| **数据目录外置** | 仓库/发布包不含个人信息；同时符合各平台应用数据规范，避免写安装目录（macOS 签名/只读卷、Windows Program Files 权限） |
| **业务逻辑与 I/O 分离** | `core/` 可直接被单元测试与可选 CLI 复用，且能与 `legacy/auto_submit_reference.py` 做逐函数等价比对 |
| **内置链接移除** | 旧版硬编码了某次真实活动的 token；桌面版改为用户填写 + 本地保存「上次链接」，行为等价但不带活动痕迹 |

## 事件类型

| kind | payload | 消费方 |
|---|---|---|
| `log` | `{ts, level, text}` | 日志视图（分级着色 / 可选脱敏） |
| `state` | 统计字段字典 | 状态卡、任务标签、按钮可用性 |
| `form` | 表单结构（含 `fields` / `rules`） | 表单信息区、动态字段控件 |
| `preview` | `{rows, attributes}` | 提交数据预览表 |
| `finished` | 运行摘要 | 结束提示 |
| `question` | 缺项弹窗请求 | 弹窗 → `GuiInputProvider.answer()` |
| `form_result` | 界面主动「读取表单」的结果 | 表单信息区（不阻塞主线程） |

## 并发与锁

- `ConfigStore` / `ProfileStore` / `Settings` 各自持 `RLock`，写入用「备份 + 唯一临时文件 + `os.replace`」。
- 档案切换时 `ProfileStore.apply()` 串行化「读取 → 写配置 → 更新 active」，避免多任务并发覆盖。
- 引擎线程只通过队列与主线程通信；Tk 控件只由主线程修改。
