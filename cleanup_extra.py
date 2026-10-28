#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""清理「CNN課程備份」裡多出來的檔案 (來源已刪除, 備份卻還留著)。

為什麼要透過雲端:
    本機 clasp 憑證只有 drive.file + drive.metadata.readonly, 沒有刪除權限
    (備份檔是 Apps Script 建立的, 本機這個 App 動不了), 所以刪除一樣要交給
    cloneBridge Web App (Apps Script, 完整 Drive 權限)。

安全護欄:
    雲端只會刪「來源沒有的檔案」, 判斷方式與 clone_cnn.py 驗證時的「多餘」完全相同,
    所以來源還有的檔案不可能被誤刪。刪除是移到垃圾桶, 隨時可還原。預設只列出、不刪。

用法:
    python cleanup_extra.py                  # 只列出多餘的檔案 (不刪)
    python cleanup_extra.py --trash          # 刪除全部多餘的檔案 (移到垃圾桶)
    python cleanup_extra.py --trash --name "Image Recognition-20261005T102736Z-1-001.zip"

輸出關鍵字:
    RESULT: NO_EXTRA 沒有多餘檔案
    RESULT: FOUND_EXTRA 有 N 個多餘檔案 (只列出時)
    RESULT: TRASHED 已刪除 N 個多餘檔案
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import backup_cnn_drive as b  # noqa: E402


def bridge_call(action, name="", timeout=300):
    """呼叫 cloneBridge Web App (action=extra 只列, action=trash 才刪)。"""
    url = b.bridge_url()
    secret = b.bridge_secret()
    params = {"action": action, "secret": secret}
    if name:
        params["name"] = name
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "clonecnn/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode(errors="replace")
        return json.loads(body), None
    except urllib.error.HTTPError as exc:
        return None, "HTTP %d: %s" % (exc.code, exc.read().decode(errors="replace")[:300])
    except Exception as exc:  # noqa: BLE001
        return None, str(exc)


def main():
    ap = argparse.ArgumentParser(description="清理 CNN 備份裡多餘的檔案 (來源已刪除的)")
    ap.add_argument("--trash", action="store_true", help="真的刪除 (移到垃圾桶); 不加就只列出")
    ap.add_argument("--name", default="", help="只處理這個檔名 (相對路徑或檔名)")
    args = ap.parse_args()

    print("=" * 64)
    print("CNN 課程備份 — 清理多餘檔案" + (" (實際刪除)" if args.trash else " (只列出)"))
    print("=" * 64)
    if args.name:
        print("  只處理: %s" % args.name)

    out, err = bridge_call("trash" if args.trash else "extra", args.name)
    if err:
        print("❌ 呼叫失敗: %s" % err)
        print("RESULT: BRIDGE_ERROR")
        return 3
    if not out.get("ok"):
        print("❌ 雲端回報: %s" % out.get("error"))
        print("RESULT: BRIDGE_ERROR")
        return 3

    if not args.trash:
        paths = out.get("extra", [])
        print("\n多餘的檔案 (來源已刪除, 備份還留著): %d 個" % len(paths))
        for p in paths:
            print("  + " + p)
        if paths:
            print("\n要刪除請加 --trash (只會移到垃圾桶, 可還原)")
            print("RESULT: FOUND_EXTRA 有 %d 個多餘檔案" % len(paths))
            return 2
        print("\nRESULT: NO_EXTRA 沒有多餘檔案")
        return 0

    trashed = out.get("trashed", [])
    skipped = out.get("skipped", [])
    print("\n已刪除 (移到垃圾桶): %d 個" % len(trashed))
    for p in trashed:
        print("  - " + p)
    if skipped:
        print("未符合 --name, 保留: %d 個" % len(skipped))
    print("備份裡原本多餘的檔案共 %s 個" % out.get("extraTotal", "?"))
    print("\n建議再驗證一次: python clone_cnn.py --verify")
    if trashed:
        print("RESULT: TRASHED 已刪除 %d 個多餘檔案" % len(trashed))
    else:
        print("RESULT: NO_EXTRA 沒有可刪的多餘檔案")
    return 0


if __name__ == "__main__":
    sys.exit(main())
