# 方案 B 图标资源

当前资源采用叠放档案卡与连接节点的方案 B 图形。`app.svg` 是可编辑源稿，二进制资源由它导出。

| 平台 | 文件 | 说明 |
|---|---|---|
| macOS | `packaging/icons/app.icns` | 多尺寸 icns；构建脚本存在时自动传给 PyInstaller |
| Windows | `packaging/icons/app.ico` | 含 16 至 256 像素的七种尺寸 |
| 应用内 | `app.png`、`app-48.png`、`app-72.png`、`app-96.png` | 1,024 像素母图和预先抗锯齿缩放的顶栏图标 |

从 `app.svg` 导出 1,024 × 1,024 像素的 RGBA PNG，再通过高质量重采样生成顶栏和系统图标。应用按 Tk 的显示缩放选择顶栏资源。

图标为本项目原创几何图形，不包含个人信息、表单 token 或第三方品牌标识。
