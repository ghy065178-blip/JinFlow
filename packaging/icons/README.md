# 方案 B 图标资源

当前资源采用叠放档案卡与连接节点的方案 B 图形。`app.svg` 是可编辑源稿，二进制资源由它导出。

| 平台 | 文件 | 说明 |
|---|---|---|
| macOS | `packaging/icons/app.icns` | 多尺寸 icns；构建脚本存在时自动传给 PyInstaller |
| Windows | `packaging/icons/app.ico` | 含 16/32/48/256 尺寸的 ico |

文件缺失时构建脚本会跳过 `--icon`，使用系统默认图标，功能不受影响。图标资源不参与运行时加载。

图标为本项目原创几何图形，不包含个人信息、表单 token 或第三方品牌标识。
