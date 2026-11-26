# legacy/ · 旧版参考实现

`auto_submit_reference.py` 是旧版 `auto_submit.py` 的**只读副本**，仅用于
`tests/test_legacy_parity.py` 的等价性对照：验证桌面版的链接解析、联动规则、
配置翻译、`entryAttributes` 构建、请求体与提交判定与原版输出一致。

**唯一改动**：`DEFAULT_TOKEN`（原为某次真实活动的表单 token，此处不复述其值）已置空，
以满足「仓库与发布包不含内置个人信息 / 活动链接」的要求。

约束：

- 该文件**不参与桌面版任何运行时逻辑**，不会被 import 到 `src/jsj_desktop/`；
- 请勿在此目录放入 `报名信息.json`、`个人档案.json`、备份或任何真实数据；
- 请勿直接运行它（它仍带终端交互与提交逻辑）；需要终端能力请用
  `python -m jsj_desktop --cli`；
- 修改 `src/jsj_desktop/core/` 的业务逻辑后，必须保证等价性测试继续通过。

旧版 `control_panel.py` / `control_panel.html` 未收录：其界面功能已在桌面版
原生窗口中重新实现，逐项对照见 `docs/FEATURE_PARITY.md`。
