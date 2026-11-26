# 贡献指南

## 开发准备

```bash
git clone <your-repo-url>
cd jinshuju-registration-desktop
python -m pip install -r requirements-dev.txt
python -m pip install -e .
python -m jsj_desktop          # 图形界面
python tools/smoke_test.py     # 自检
```

Python 3.11+（含 Tcl/Tk）。运行时零第三方依赖，请不要在 `src/` 中引入
需要二进制轮子的库——项目必须能在 Windows ARM64 上原生构建。

## 提交前检查

```bash
python -m unittest discover -s tests -t . -v
python tools/check_no_pii.py --strict
python -m jsj_desktop --self-test
```

任何改动 `src/jsj_desktop/core/` 的 PR 都必须保证 `tests/test_legacy_parity.py`
与 `tests/test_mapping.py` 通过；这两项保证「业务逻辑与数据处理结果不变」。

## 隐私红线

- **绝不提交** `报名信息*.json`、`个人档案*.json`、`*.backup.json`、
  `*.log`、`panel_url.txt`、`多开任务/` 或任何含真实姓名/学号/电话/表单 token 的文件。
- 测试与示例只用合成数据、占位符；新增样例请放在 `tests/fixtures/` 或 `examples/`。
- 不要在 Issue / PR / 日志片段里粘贴真实报名信息；必要时先脱敏。

## 代码约定

- UTF-8、LF（`*.bat` 除外）、4 空格缩进；业务逻辑在 `core/`，界面在 `ui/`，
  两者只通过 `tasks/manager.py` 的事件队列交互。
- 新增配置项要同步更新 `docs/CONFIGURATION.md`、`README.md` 与相关测试。
- 新增平台或发布包要同步更新 `.github/workflows/release.yml` 与 `docs/RELEASE.md`。
- 提交信息建议用中文简述，PR 说明改动动机与验证方式。

## 合规

请确认你有权提交相应代码；本项目不是金数据官方产品，贡献内容不得包含
绕过验证码、批量刷单或干扰平台服务的能力。
