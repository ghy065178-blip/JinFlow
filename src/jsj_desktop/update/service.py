# -*- coding: utf-8 -*-
"""升级流程编排：检查 → 下载 → 校验 → 解包 → 验证 → 安装/切换 → 重启。

全过程只写临时目录与安装位置；用户数据目录中的报名信息、档案、任务配置
一律不读不写（除了把源码运行的新版暂存到 updates/）。异常统一为
UpdateError 子类，交给界面/CLI 展示失败提示。
"""
from pathlib import Path

from . import client, installer
from .errors import UpdateError


def _noop(stage, percent, text):
    pass


def check_for_update(**kwargs):
    return client.check_for_update(**kwargs)


def prepare_update(check, progress=None, work_dir=None, fetcher=None,
                   opener=None):
    """下载并验证发布包，返回可直接安装的结构；失败时删除临时文件。"""
    progress = progress or _noop
    if not check.ok:
        raise check.error or UpdateError("检查更新失败。")
    if not check.update_available:
        raise UpdateError("当前已是最新版本，无需下载。")
    if not check.can_update or not check.asset:
        raise UpdateError(check.reason or "当前环境不支持自动升级。",
                          code="cannot-apply",
                          hint="请在 Releases 页面手动下载：%s"
                               % check.manual_url)

    work = Path(work_dir or installer.make_workdir())
    try:
        progress("checksum", 2, "正在获取 SHA256 校验和…")
        checksum = client.resolve_checksum(check.info, check.asset,
                                           fetcher=fetcher)
        progress("download", 5, "正在下载 %s…" % check.asset["name"])

        def on_progress(done, total):
            pct = 5 + int(75 * done / total) if total else 45
            progress("download", min(pct, 80),
                     "正在下载 %s（%.1f MB）"
                     % (check.asset["name"], done / 1048576.0))

        archive = work / check.asset["name"]
        client.download_file(check.asset["url"], archive,
                             progress=on_progress, opener=opener)
        progress("verify", 82, "正在校验下载文件…")
        client.verify_download(archive, checksum["sha256"])
        progress("extract", 86, "正在解包…")
        root = work / "package"
        installer.extract_zip(archive, root)
        progress("validate", 92, "正在核对版本与平台…")
        package = installer.validate_package(root, check.target,
                                             check.package_version)
        return {"work_dir": str(work), "archive": str(archive),
                "package": package, "checksum": checksum,
                "asset": check.asset}
    except Exception:
        if work_dir is None:
            installer.cleanup_workdir(work)
        raise


def apply_update(check=None, progress=None, relaunch=True, runner=None,
                 work_dir=None, fetcher=None, opener=None, sources=None,
                 info=None, **check_kwargs):
    """执行完整升级；返回结构化结果，或抛出 UpdateError 子类。"""
    progress = progress or _noop
    check = check or check_for_update(fetcher=fetcher, sources=sources,
                                      info=info, **check_kwargs)
    if not check.ok:
        raise check.error or UpdateError("检查更新失败。")
    if not check.update_available:
        return {"ok": True, "noop": True, "mode": "none",
                "message": check.reason, "current_version": check.current_version,
                "latest_version": check.latest_version}

    prepared = None
    try:
        prepared = prepare_update(check, progress=progress,
                                  work_dir=work_dir, fetcher=fetcher,
                                  opener=opener)
        ctx = installer.install_context()
        plan = installer.plan_install(ctx, prepared["package"],
                                      check.package_version)
        progress("install", 95, plan["note"])
        result = installer.apply_install(plan, relaunch=relaunch, runner=runner)
        if not result.get("pending"):
            progress("done", 100, result["message"])
        result.update({
            "noop": False,
            "current_version": check.current_version,
            "latest_version": check.latest_version,
            "latest_revision": check.latest_revision,
            "target": check.target,
            "asset": check.asset["name"],
            "checksum_source": prepared["checksum"]["source"],
            "sha256": prepared["checksum"]["sha256"],
            "channel": check.source,
        })
        return result
    finally:
        if prepared and work_dir is None:
            installer.cleanup_workdir(prepared["work_dir"])
