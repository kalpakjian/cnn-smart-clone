#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""從 Apps Script 專案移除指定的雲端檔案 (會改動雲端專案, 請確認檔名)。

用法:
    python gs_remove_file.py <檔名不含副檔名>   # 例: python gs_remove_file.py remote_startSmartCloneCNN
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_cnn_drive as b  # noqa: E402
import gs_files  # noqa: E402


def put_content(files):
    url = ("https://script.googleapis.com/v1/projects/%s/content"
           % urllib.parse.quote(gs_files.SCRIPT_ID, safe=""))
    payload = json.dumps({"files": files}).encode()
    req = urllib.request.Request(url, data=payload, method="PUT", headers={
        "Authorization": "Bearer " + b.access_token(),
        "Content-Type": "application/json",
    })
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print("PUT 失敗: HTTP %d: %s" % (exc.code, exc.read().decode(errors="replace")[:500]))
        return None


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    target = sys.argv[1]

    out = gs_files.fetch_content()
    if out is None:
        return 1
    files = out.get("files", [])
    keep = [f for f in files if f.get("name") != target]
    if len(keep) == len(files):
        print("雲端沒有這個檔案: %s (未變更)" % target)
        return 2

    print("移除: %s" % target)
    print("  原本: %s" % [f.get("name") for f in files])
    print("  之後: %s" % [f.get("name") for f in keep])
    res = put_content(keep)
    if res is None:
        return 1
    print("✅ 完成, 雲端現在有 %d 個檔案" % len(res.get("files", [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
