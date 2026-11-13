#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_site.py · 重建站点并推送到 GitHub

顺序：07_site.py 重建 data/ + site/ → git add → commit → push。
推上去之后 Cloudflare Pages 会自动部署（在 CF 后台把仓库连上即可，见 README）。

用法：
    python scripts/deploy_site.py            # 重建并推送
    python scripts/deploy_site.py --dry-run  # 只重建，不碰 git
"""

import sys
import subprocess
import datetime
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = Path(__file__).resolve().parent.parent

# 本机访问 github.com 必须走 127.0.0.1:7897 这个本地代理：直连会被重置或超时，
# 而 ~/.gitconfig 里配的 7890 根本没人在听。所以显式指定，不改全局配置。
PROXY = ["-c", "http.proxy=http://127.0.0.1:7897",
         "-c", "https.proxy=http://127.0.0.1:7897"]

# 只有这些网络层错误才值得换一条路重试；认证失败、冲突之类重试没意义
NET_ERRS = ("unable to access", "connection was reset", "timed out",
            "could not resolve host", "failed to connect",
            "connection refused", "recv failure", "send failure",
            "couldn't connect", "network is unreachable")


def git(*args):
    """跑 git：先走上面的代理，网络层失败才退回直连重试一次。

    顺序不能颠倒——直连是默认不通的那条，代理没开的某一天靠它兜底。
    """
    last = (1, "")
    for extra in (PROXY, []):
        r = subprocess.run(["git", *extra, *args], cwd=str(ROOT),
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        last = (r.returncode, out)
        if r.returncode == 0:
            return last
        low = out.lower()
        if not any(e in low for e in NET_ERRS):
            return last
    return last


TRACK = ["data", "site", "scripts", "README.md",
         "pipeline.json", ".gitignore"]


def main():
    dry = "--dry-run" in sys.argv

    print("1/3 重建站点")
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "07_site.py")],
                       cwd=str(ROOT))
    if r.returncode != 0:
        print("✗ 07_site.py 失败，放弃推送")
        return 1

    if dry:
        print("--dry-run：到此为止，不碰 git")
        return 0

    print("2/3 检查远端")
    code, out = git("remote", "get-url", "origin")
    if code != 0:
        print("✗ 这个仓库还没有 origin。先建好 GitHub 仓库，然后：")
        print("    git remote add origin https://github.com/<你的用户名>/<仓库名>.git")
        print("    python scripts/deploy_site.py")
        return 1

    print("    origin =", out.strip())

    print("3/3 提交并推送")
    git("add", *TRACK)
    code, out = git("status", "--porcelain")
    if not out.strip():
        print("没有变化，不用推送")
        return 0

    msg = "site: 更新至 %s" % datetime.date.today().isoformat()
    code, out = git("commit", "-m", msg)
    if code != 0:
        print("✗ commit 失败：\n" + out)
        return 1

    code, out = git("push", "-u", "origin", "HEAD")
    if code != 0:
        print("✗ push 失败：\n" + out)
        print("（首次推送建议先跑 git push -u origin master 看看 GCM 的浏览器授权）")
        return 1

    print("✓ 已推送，Cloudflare Pages 随后会自动部署")
    return 0


if __name__ == "__main__":
    sys.exit(main())
