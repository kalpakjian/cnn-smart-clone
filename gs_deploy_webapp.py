#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""重新部署「cloneBridge」Web App, 並把網址寫入 bridge_url.txt。

用法:
    python gs_deploy_webapp.py

產出:
    https://script.google.com/macros/s/<deploymentId>/exec

踩坑 (2026/10/07 修好):
    Apps Script API 的 projects.deployments.create 不接受 deploymentConfig / entryPoints
    這兩個欄位 (會回 HTTP 400 Unknown name "deploymentConfig"/"entryPoints"),
    所以「建立版本」用 API、「建立/更新部署」交給 clasp:
      - 已有部署 (bridge_url.txt 內的 deploymentId) -> clasp deploy -i <id> -V <版本>
        → 網址不變, 也不會殘留一堆舊部署
      - 沒有部署 -> clasp deploy -V <版本> 建立新的, 取回新網址
"""

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_cnn_drive as b  # noqa: E402
import gs_files  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
URL_FILE = os.path.join(HERE, "bridge_url.txt")
DEPLOYED_RE = re.compile(r"Deployed\s+(\S+)")


def current_deployment_id():
    """從 bridge_url.txt 取出現有部署 ID (沒有就回 None)。"""
    if not os.path.exists(URL_FILE):
        return None
    with open(URL_FILE, "r", encoding="utf-8-sig") as fh:
        url = fh.read().strip()
    m = re.search(r"/macros/s/([^/]+)/", url)
    return m.group(1) if m else None


def clasp_deploy(version, deployment_id):
    """用 clasp 建立/更新 Web App 部署 (API 做不到, 見檔頭說明)。"""
    args = ["clasp", "deploy", "-V", str(version)]
    if deployment_id:
        args += ["-i", deployment_id]
    # 描述含空白 -> 一定要自己加引號 (shell=True 走 cmd.exe, 不會自動加)
    args += ["-d", '"clone bridge v%s"' % version]
    cmd = " ".join(args)
    print("執行: %s" % cmd)
    proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, shell=True)
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    if out:
        print(out)
    failed = proc.returncode != 0 or "error:" in out.lower()
    return out, (1 if failed else 0)


def bridge_secret():
    return b.bridge_secret()


def ping(url):
    """部署完立刻 ping 一次, 確認 Web App 真的活著。"""
    full = url + "?" + urllib.parse.urlencode({"action": "ping", "secret": bridge_secret()})
    req = urllib.request.Request(full, headers={"User-Agent": "clonecnn/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode(errors="replace")
        return json.loads(body).get("ok") is True, body[:200]
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def api_post(path, body):
    url = "https://script.googleapis.com/v1" + path
    payload = json.dumps(body).encode()
    req = urllib.request.Request(url, data=payload, method="POST", headers={
        "Authorization": "Bearer " + b.access_token(),
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode()), None
    except urllib.error.HTTPError as exc:
        return None, "HTTP %d: %s" % (exc.code, exc.read().decode(errors="replace")[:800])


def main():
    sid = urllib.parse.quote(gs_files.SCRIPT_ID, safe="")

    # 1. 建一個版本 (部署需要 versionNumber)
    ver, err = api_post("/projects/%s/versions" % sid, {"description": "clone bridge"})
    if err:
        print("建立版本失敗: %s" % err)
        return 1
    version = ver.get("versionNumber")
    print("已建立版本: @%s" % version)

    # 2. 建立/更新 Web App 部署 (交給 clasp, 見檔頭說明)
    dep_id = current_deployment_id()
    if dep_id:
        print("沿用既有部署: %s (網址不變)" % dep_id)
    else:
        print("找不到既有部署, 建立新的部署")
    out, code = clasp_deploy(version, dep_id)
    if code != 0:
        print("clasp deploy 失敗 (exit %d)" % code)
        return 2
    m = DEPLOYED_RE.search(out)
    if m:
        dep_id = m.group(1)
    if not dep_id:
        print("無法從 clasp 輸出取得 deploymentId")
        return 2

    url = "https://script.google.com/macros/s/%s/exec" % dep_id
    print("✅ 部署完成")
    print("  deploymentId : %s" % dep_id)
    print("  URL          : %s" % url)

    # 3. 寫入網址檔 (UTF-8 不加 BOM)
    with open(URL_FILE, "w", encoding="utf-8", newline="") as fh:
        fh.write(url + "\n")
    print("已寫入 %s" % URL_FILE)

    # 4. 立刻 ping 驗證
    ok, detail = ping(url)
    print("  ping         : %s" % ("BRIDGE_OK ✅" if ok else "失敗 ✗ %s" % detail))
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
