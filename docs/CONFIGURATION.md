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
| 界面主题 | 跟随系统 | 「设置与关于」/ `settings.json` 的 `theme_mode` |
| 启动时自动检查更新 | 开 | 「设置与关于」/ `settings.json` 的 `check_update_on_startup`（1.2.0） |
| 最新版本 / 升级目标 | `1.3.0` | `update/latest.json`（只读发布通道） |
| 北京时间时区 | `Asia/Shanghai`（缺少时区库时 UTC+8） | `core/constants.py` |
| User-Agent | 与旧脚本一致 | `core/constants.py` |

## 2. 环境变量

| 变量 | 作用 |
|---|---|
| `JSJ_DATA_DIR` | 覆盖用户数据目录（便携版、测试、CI）。未设置时按平台默认路径；1.2.0 起也是新版暂存目录 `<数据目录>/updates/` 的根目录 |
| `JSJ_UPDATE_MANIFEST_URL` | 1.2.0：指定**唯一**更新清单来源（镜像 / 离线验证 / 企业内网），设置后不再访问其它通道；命令行等价参数 `--manifest-url` |
| `SSL_CERT_FILE` | 冻结版 macOS 由 `packaging/entry_point.py` 自动指向随包 `certs/cacert.pem`；检查更新同样走系统证书校验，不关闭验证 |
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
  "theme_mode": "system",
  "check_update_on_startup": true,
  "tasks": [{"id": "t1", "name": "任务 1", "profile_id": "p1"}]
}
```

- `check_update_on_startup` 缺省为 `true`。旧版 `settings.json` 中明确设为 `false`
  的用户继续关闭启动检查。
- `theme_mode` 可取 `dark`、`light`、`system`，默认 `system`；旧版配置缺少该键时自动跟随系统。

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

## 6. 更新通道与版本清单（1.3.0）

`update/latest.json` 是版本无关的只读清单，历史版本与 1.3.0 使用同一格式：

```json
{
  "schema": 1,
  "latest_version": "1.3.0",
  "tag": "v1.3.0",
  "min_supported_version": "1.0.0",
  "upgrade_target": "1.3.0",
  "legacy_versions": ["1.0.0", "1.0.1", "1.0.2", "1.0.3"],
  "assets": {"macos-arm64": {"zip": "JinshujuDesktop-macos-arm64.zip"}},
  "checksums_asset": "SHA256SUMS.txt",
  "download_base": ".../releases/download/v1.3.0/"
}
```

- 仓库中的模板 `sha256` 为空；Release 工作流调用
  `tools/generate_update_manifest.py` 从 `SHA256SUMS.txt` 填入真实哈希，
  生成随 Release 发布的 `latest.json`。
- 应用内默认依次探测：静态清单 → GitHub Releases API → Release 资产清单，
  取版本号最高者；全部失败才回退随包清单并禁止自动安装。若设置了
  `JSJ_UPDATE_MANIFEST_URL`，则只使用该地址作为唯一来源。
- `tools/check_update_channel.py --offline` 在 CI / Release 校验四处版本号一致、
  四平台资产名、`legacy_upgrade_paths` 与校验和覆盖。
- 新版本暂存目录：`<数据目录>/updates/<版本>/<target>/`；旧安装备份为
  `JinshujuDesktop.app.backup-<旧版本>` 或 `JinshujuDesktop.backup-<旧版本>`。
  这些目录只含程序文件，不含报名信息。

## 7. 敏感数据处理

- 上面两个数据文件在 `.gitignore` 中按中文名与英文名同时屏蔽；发布包构建时会额外扫描。
- 示例与测试只用 `<…占位>`、`EXAMPLE` 等占位值，见 `examples/` 与 `tests/fixtures/`。
- 日志默认不落盘；导出路径由用户选择。
