# 隐私与敏感数据防护

## 原则

**仓库、发布包与源代码中不含任何内置个人信息或敏感数据；用户数据只存在于用户自己的机器。**

旧版目录里出现过 `个人档案.json`、`报名信息.json`、各自的 `.backup.json`、`多开任务/task_*/报名信息.json`、`panel_url.txt`，以及 `auto_submit.py` 中内置的真实活动 token。这些**全部不进入新仓库与发布包**。

## 防护层次

### 1. 代码层

- 无内置姓名、学号、电话、表单 token 或活动链接；`DEFAULT_TOKEN` 已从参考实现置空，桌面版完全移除该常量。
- 首次使用必须填写链接；之后仅复用**本地**保存的上次链接。
- 旧版 `field_rules.json` / `form_structure.json` / `金数据表单字段分析.html` 等真实活动分析产物不入库；测试改用 `tests/fixtures/` 中的合成 GraphQL 响应。
- 运行日志默认只在内存；导出、档案导入导出均由用户显式选择路径。
- 提供「日志脱敏显示」开关（手机号、长数字掩码），只影响显示，不改变提交数据。

### 2. 仓库层

`.gitignore` 屏蔽：

```
报名信息*.json / 个人档案*.json / *.backup.json / profiles*.json / settings.json
panel_url.txt / control_panel_error.log / *.log / 多开任务/ / 多开任务/task_*/
/tasks/ / /logs/ / /data/ / .env / *.pem / *.key / credentials*.json
```

`legacy/auto_submit_reference.py` 是旧脚本的只读参考副本，已移除内置 token，且只被等价性测试加载，不参与任何运行时逻辑。

### 3. 工具层

`tools/check_no_pii.py` 检查：

| 类别 | 规则 |
|---|---|
| 禁止文件名 | `报名信息*.json`、`个人档案*.json`、`*.backup.json`、`panel_url.txt`、`control_panel_error.log`、`多开任务/`、`.env`、`*.pem`、私钥等 |
| 真实活动链接 | `https://<host>/f/<token>` 且 token 不是 `xxxxx` / `EXAMPLE` 等占位值 |
| 内置 token | `DEFAULT_TOKEN = "非空"` |
| 手机号 / 身份证号 | `1[3-9]\d{9}`、18 位证件号 |
| JSON 个人信息键 | `姓名/学号/电话/手机号/身份证` 等键出现非占位值；英文键出现号码型值 |
| 硬编码凭据 | `api_key/password/access_token = 长字符串` |

`tests/`、`examples/` 内的合成链接按设计豁免（这些目录只放测试数据），其余路径一律严格检查。

**运行时数据豁免**：PyInstaller 冻结包会携带 Tcl/Tk 自带的编码表
（`_tcl_data/` / `_tk_data/` 下的 `.enc` 等，以及随包 CA 根证书
`certs/cacert.pem`），其中含大量纯数字/Base64 文本，并非用户数据。
这些路径只跳过「内容模式匹配」，**文件名禁用检查仍然生效**；仅 `certs/`
目录下的 `cacert.pem` 豁免 `.pem` 私钥规则，其它 `.pem`（含私钥）仍被拦截；
任何随包携带的 `报名信息.json` / `个人档案.json` 依旧会被拦截。
该豁免有专门的回归测试覆盖（模拟发布包含编码表 → 不误报，含真实档案 → 仍拦截）。

### 4. CI / 发布层

- `ci.yml` 每个平台都执行 `python tools/check_no_pii.py --strict`，失败即中断。
- `release.yml` 在打包后执行 `--strict --artifact <发布包>`，扫描 zip / 目录内的全部文本条目；
  对 `.dmg` 会在 macOS 上只读挂载后按目录扫描（非 macOS 不生成 DMG，挂载失败一律视为扫描失败）。
- `packaging/build.py` 在生成归档前再次调用扫描器，并写出 `BUILD_INFO.txt` 与 `SHA256SUMS.txt`。
- `tests/test_no_pii.py` 把「仓库干净」固化为单元测试，防止后续提交误带数据。

## 数据生命周期

| 数据 | 产生 | 存储 | 删除 |
|---|---|---|---|
| 报名信息 | 用户填写 / 导入 | `<数据目录>/tasks/<id>/报名信息.json` + 备份 | 用户自行删除数据目录 |
| 多人档案 | 用户新建 / 导入 | `profiles.json` + 备份 | 界面「删除」或删除文件 |
| 运行日志 | 运行时内存 | 不落盘（除非用户导出） | 关闭程序即消失 |
| 导出的日志/档案 | 用户显式导出 | 用户自选路径 | 用户自行管理 |
| 表单结构与选项 | 运行时在线拉取 | 内存 | 不落盘 |

程序不上传、不遥测、不写云端；除目标表单站点的 GraphQL 请求外不发起其它网络请求。

## 上报与安全

若怀疑个人信息被误提交到仓库，请立即：

1. 从工作区删除文件并 `git rm --cached`（必要时用 `git filter-repo` 清理历史并强制推送）；
2. 轮换任何可能泄露的凭据；
3. 运行 `python tools/check_no_pii.py --strict` 确认干净；
4. 在私有渠道告知维护者，不要在公开 Issue 中粘贴真实数据。
