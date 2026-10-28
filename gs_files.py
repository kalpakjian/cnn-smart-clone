#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""列出 Apps Script 專案「雲端上」的檔案清單 (唯讀), 用來確認 clasp push 不會覆蓋雲端既有檔案。

用法:
    python gs_files.py
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_cnn_drive as b  # noqa: E402

SCRIPT_ID = b.clasp_script_id()


def fetch_content():
    url = ("https://script.googleapis.com/v1/projects/%s/content"
           % urllib.parse.quote(SCRIPT_ID, safe=""))
    req = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + b.access_token(),
    })
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        print("查詢失敗: HTTP %d: %s" % (exc.code, exc.read().decode(errors="replace")[:400]))
        return None


def main():
    name = sys.argv[1] if len(sys.argv) > 1 else None
    outpath = sys.argv[2] if len(sys.argv) > 2 else None

    out = fetch_content()
    if out is None:
        return 1

    files = out.get("files", [])
    if name:
        for f in files:
            if f.get("name") == name:
                src = f.get("source", "")
                if outpath:
                    with open(outpath, "w", encoding="utf-8", newline="") as fh:
                        fh.write(src)
                    print("已寫出雲端檔案 %s -> %s (%d chars)" % (name, outpath, len(src)))
                else:
                    print(src)
                return 0
        print("雲端找不到檔案: %s" % name)
        return 2

    print("雲端檔案數: %d" % len(files))
    for f in files:
        src = f.get("source", "")
        print("  %-28s %-12s %6d chars" % (f.get("name"), f.get("type"), len(src)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
