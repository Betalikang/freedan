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
import time
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

# 第二条路：把代理显式清空。**必须显式清**，只传空列表的话 git 会继续用
# ~/.gitconfig 里那个死的 7890，看着像"直连"其实不是。
NO_PROXY = ["-c", "http.proxy=", "-c", "https.proxy="]

# 只有这些网络层错误才值得换一条路重试；认证失败、冲突之类重试没意义
NET_ERRS = ("unable to access", "connection was reset", "timed out",
            "could not resolve host", "failed to connect",
            "connection refused", "recv failure", "send failure",
            "couldn't connect", "network is unreachable")


def git(*args):
    """跑 git：先走代理，网络层失败才清空代理重试一次。

    顺序不能颠倒——两条路都可能通，也可能都不通，所以都要试。
    """
    last = (1, "")
    for extra in (PROXY, NO_PROXY):
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


TRACK = ["data", "content", "site", "scripts", "README.md",
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

    # 本机两条出口（7897 代理 / 直连）都会间歇性抽风，实测同一时刻
    # 可能一条全通另一条全挂。无人值守必须重试，否则某天推不上去
    # 站点就静默停更，而视频那边还是好的，很难发现。
    for attempt in range(1, 4):
        code, out = git("push", "-u", "origin", "HEAD")
        if code == 0:
            print("✓ 已推送")
            return 0
        if attempt < 3:
            wait = 8 * attempt
            print(f"  push 第 {attempt}/3 次失败，{wait}s 后重试")
            print("  " + out.strip().split("\n")[0][:120])
            time.sleep(wait)
    print("✗ push 三次都失败：\n" + out)
    return 1


if __name__ == "__main__":
    sys.exit(main())
