# 配置、数据格式与环境变量

## 1. 配置来源与优先级

1. **界面输入**（本次运行参数）→ 2. **本任务 `报名信息.json`**（报名信息与上次链接）→ 3. **代码默认值**。
   程序不会从仓库或安装目录读取任何内置报名数据。

| 项 | 默认值 | 位置 |
|---|---|---|
| 表单链接 | 空（必须由用户填写） | 任务控制台 / `报名信息.json` 的 `表单链接` |
| 开放时间来源 | `1`（表单返回时间） | 任务控制台 |
| 提前量 | `-6` 秒 | 任务控制台 |
| 提交间隔 | `0.05` 秒 | 任务控制台 |
| 冲刺时长 | `40` 秒 | 任务控制台 |
| 快速模式 / 仅演练 / 逐项确认 | 关 | 任务控制台 |
| 自动应答缺项 | 开 | 任务控制台 |
| 日志脱敏显示 | 关 | 实时日志 / `settings.json` |
| 北京时间时区 | UTC+8（固定） | `core/constants.py` |
| User-Agent | 与旧脚本一致 | `core/constants.py` |

## 2. 环境变量

| 变量 | 作用 |
|---|---|
| `JSJ_DATA_DIR` | 覆盖用户数据目录（便携版、测试、CI）。未设置时按平台默认路径 |
| `PYTHONIOENCODING` | 可选；旧 `.bat` 会设为 utf-8，桌面版由内部 UTF-8 事件队列处理，无需设置 |
| `PYTHONPATH` | 源码运行时指向 `src/`（或先 `pip install -e .`） |

## 3. 数据目录

```
Windows : %APPDATA%\JinshujuDesktop\
macOS   : ~/Library/Application Support/JinshujuDesktop/
Linux   : $XDG_DATA_HOME/jinshuju-desktop/ 或 ~/.local/share/jinshuju-desktop/
```

```
<数据目录>/
├── settings.json
├── profiles.json
├── profiles.backup.json
├── logs/                       （预留；日志默认只在内存）
└── tasks/
    ├── t1/报名信息.json
    ├── t1/报名信息.backup.json
    └── t2/...
```

所有写入流程：`若文件存在 → copy2 到 .backup.json → 写唯一临时文件 → os.replace 原子替换`。
`ProfileStore` 另对「读取 → 写配置 → 更新 active」整段加锁，避免多任务并发覆盖。

## 4. 文件格式

### `报名信息.json`（与旧版完全兼容）

键为**表单字段的中文标签**，值为中文选项名 / 文本 / 多选数组；`表单链接` 保存本次链接。

```json
{
  "表单链接": "https://jsj.top/f/xxxxx",
  "姓名": "<姓名占位>",
  "学号": "<学号占位>",
  "培养层次": "硕士",
  "年级": "2024级",
  "班级": "甲班",
  "电话": "<电话占位>",
  "可多选": ["选项甲"]
}
```

> 上例为占位符；真实文件中是用户自己填写的值。**该文件绝不入库/入包**。

### `profiles.json`（与旧版「个人档案.json」兼容）

```json
{
  "active": "p1",
  "profiles": [
    {"id": "p1", "name": "档案甲", "values": {"姓名": "<姓名占位>", "学号": "<学号占位>"}}
  ]
}
```

- `active` 记录最近一次切换的档案；每个任务另有 `settings.json` 中的 `profile_id` 绑定。
- 导出文件同结构，导入时按 id 去重后合并（重复 id 会生成新 id，不覆盖已有档案）。

### `settings.json`

```json
{
  "mask_logs": false,
  "auto_scroll": true,
  "auto_reply": true,
  "tasks": [{"id": "t1", "name": "任务 1", "profile_id": "p1"}]
}
```

## 5. 提交数据格式（业务结果不变）

`core/mapping.build_attributes()` 产出的 `entryAttributes` 与旧版一致：

```json
{
  "field_1": "<姓名占位>",
  "field_3": "A1",
  "field_8": ["D1"]
}
```

即：只含**当前可见**字段；单选 = 选项编码字符串；多选 = 编码数组；文本 = 字符串；隐藏字段不出现。
`build_input()` 再包装为：

```json
{
  "formId": "<token>",
  "entryAttributes": { "...": "..." },
  "fillingDuration": 1.23,
  "forceSubmit": false,
  "hasPreferential": false
}
```

## 6. 敏感数据处理

- 上面两个数据文件在 `.gitignore` 中按中文名与英文名同时屏蔽；发布包构建时会额外扫描。
- 示例与测试只用 `<…占位>`、`EXAMPLE` 等占位值，见 `examples/` 与 `tests/fixtures/`。
- 日志默认不落盘；导出路径由用户选择。
