#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
deploy_site.py · 重建站点并推送到 GitHub

顺序：07_site.py 重建 data/ + site/ → git add → commit → push。
推上去之后 Netlify 会自动部署（在 Netlify 后台把仓库连上即可，见 README）。

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

# 本机 ~/.gitconfig 里的 http.proxy/https.proxy 指向 127.0.0.1:7890，
# 但那个端口没人监听，直连 github.com 反而是通的。所以每条 git 网络命令
# 都显式把代理清空，不改全局配置。
NO_PROXY = ["-c", "http.proxy=", "-c", "https.proxy="]

TRACK = ["data", "site", "scripts", "netlify.toml", "README.md",
         "config.json", ".gitignore"]


def git(*args, check=False):
    r = subprocess.run(["git", *NO_PROXY, *args], cwd=str(ROOT),
                       capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and r.returncode != 0:
        print((r.stdout or "") + (r.stderr or ""))
    return r.returncode, (r.stdout or "") + (r.stderr or "")


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

    print("✓ 已推送，Netlify 随后会自动部署")
    return 0


if __name__ == "__main__":
    sys.exit(main())
