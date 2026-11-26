## 改动说明

<!-- 简述做了什么、为什么 -->

## 验证

- [ ] `python -m unittest discover -s tests -t . -v` 通过
- [ ] `python tools/check_no_pii.py --strict` 通过
- [ ] `python -m jsj_desktop --self-test` 通过
- [ ] 涉及 `src/jsj_desktop/core/` 时，等价性测试与黄金数据测试仍通过
- [ ] 涉及平台/发布时，已同步 `docs/RELEASE.md` 与 workflows

## 隐私确认

- [ ] 未提交任何真实姓名、学号、电话、表单 token、档案或日志文件
- [ ] 新增样例仅使用合成数据 / 占位符

## 关联 Issue

Closes #
