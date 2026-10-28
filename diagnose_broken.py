#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""診斷 CNN 備份中「無法開啟」的檔案（唯讀，不修改雲端任何內容）。

用法:
    python diagnose_broken.py                 # 掃描全部並列出有問題的檔案
    python diagnose_broken.py --file "3 IVDC OpenCV.pdf"   # 只查特定檔名

判定「壞檔」的條件:
    - 備份檔大小為 0（空檔案）
    - 來源與備份大小不同
    - 來源與備份 md5Checksum 不同（兩邊都有值時）
    - 來源有 md5 但備份沒有（代表備份不是真正的二進位內容）
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_cnn_drive as b  # noqa: E402

FOLDER_MIME = b.FOLDER_MIME
FIELDS = ("nextPageToken,files(id,name,mimeType,size,md5Checksum,"
          "modifiedTime,appProperties,shortcutDetails)")
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"


def children(folder_id):
    items, page = [], None
    while True:
        params = {
            "q": "'%s' in parents and trashed = false" % folder_id,
            "pageSize": 1000,
            "fields": FIELDS,
            "orderBy": "folder,name",
        }
        if page:
            params["pageToken"] = page
        out = b.api("GET", "/files", params)
        items.extend(out.get("files", []))
        page = out.get("nextPageToken")
        if not page:
            return items


def walk(folder_id, prefix, files, folders):
    for it in children(folder_id):
        if it["mimeType"] == FOLDER_MIME:
            folders.add(prefix + it["name"] + "/")
            walk(it["id"], prefix + it["name"] + "/", files, folders)
        else:
            files[prefix + it["name"]] = it


def find_target():
    out = b.api("GET", "/files", {
        "q": "name = '%s' and mimeType = '%s' and 'root' in parents and trashed = false"
             % (b.TARGET_NAME, FOLDER_MIME),
        "fields": "files(id,name)",
        "pageSize": 10,
    })
    files = out.get("files", [])
    return files[0]["id"] if files else None


def size_of(item):
    return int(item["size"]) if item.get("size") is not None else None


def describe(tag, item):
    if item is None:
        print("  %s: (不存在)" % tag)
        return
    print("  %s:" % tag)
    print("    id           : %s" % item["id"])
    print("    mimeType     : %s" % item["mimeType"])
    print("    size         : %s bytes" % item.get("size", "(無)"))
    print("    md5Checksum  : %s" % item.get("md5Checksum", "(無)"))
    print("    modifiedTime : %s" % item.get("modifiedTime"))
    print("    appProperties: %s" % (item.get("appProperties") or {}))
    if item.get("shortcutDetails"):
        print("    shortcut     : %s" % item["shortcutDetails"])


def is_native(item):
    return item["mimeType"].startswith("application/vnd.google-apps.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=None, help="只檢查指定檔名 (含路徑或僅檔名)")
    args = ap.parse_args()

    dst_root = find_target()
    print("=" * 64)
    print("CNN 備份壞檔診斷 (唯讀)")
    print("=" * 64)
    if not dst_root:
        print("找不到目的地資料夾 %s" % b.TARGET_NAME)
        return 1
    print("  來源: %s" % b.source_folder_id())
    print("  目的地: %s (%s)" % (b.TARGET_NAME, dst_root))

    print("\n掃描來源...")
    src_files, src_folders = {}, set()
    walk(b.source_folder_id(), "", src_files, src_folders)
    print("  來源檔案 %d / 資料夾 %d" % (len(src_files), len(src_folders)))

    print("掃描備份...")
    dst_files, dst_folders = {}, set()
    walk(dst_root, "", dst_files, dst_folders)
    print("  備份檔案 %d / 資料夾 %d" % (len(dst_files), len(dst_folders)))

    empty_dst = [p for p, it in dst_files.items() if size_of(it) == 0]
    no_md5 = [p for p, it in dst_files.items()
              if it.get("md5Checksum") is None and not is_native(it)]

    broken = []
    for path, src in src_files.items():
        dst = dst_files.get(path)
        if dst is None:
            broken.append((path, "備份缺少此檔", src, dst))
            continue
        s_size, d_size = size_of(src), size_of(dst)
        if d_size == 0 and (s_size or 0) > 0:
            broken.append((path, "備份是 0 byte 空檔案", src, dst))
            continue
        if s_size is not None and d_size is not None and s_size != d_size:
            broken.append((path, "大小不符 (來源 %d / 備份 %d)" % (s_size, d_size), src, dst))
            continue
        if src.get("md5Checksum") and dst.get("md5Checksum") \
                and src["md5Checksum"] != dst["md5Checksum"]:
            broken.append((path, "md5 不符（內容不同）", src, dst))
            continue
        if src.get("md5Checksum") and not dst.get("md5Checksum") and not is_native(dst):
            broken.append((path, "備份沒有 md5（非真實內容）", src, dst))

    extra = [p for p in dst_files if p not in src_files]

    print("\n===== 診斷結果 =====")
    print("  備份檔案總數      : %d" % len(dst_files))
    print("  0 byte 空檔案     : %d" % len(empty_dst))
    print("  無 md5 的二進位檔 : %d" % len(no_md5))
    print("  有問題的檔案      : %d" % len(broken))
    print("  備份多餘的檔案    : %d" % len(extra))

    if args.file:
        print("\n===== 指定檔案詳細資料: %s =====" % args.file)
        hits = [p for p in set(list(src_files) + list(dst_files))
                if p == args.file or os.path.basename(p) == args.file or args.file in p]
        if not hits:
            print("  在來源與備份中都找不到符合的檔名")
        for p in sorted(hits):
            print("\n  路徑: %s" % p)
            describe("來源", src_files.get(p))
            describe("備份", dst_files.get(p))

    if broken:
        print("\n===== 有問題的檔案清單 (前 40 筆) =====")
        for path, why, src, dst in broken[:40]:
            print("  ! %s" % path)
            print("      原因: %s" % why)
            print("      來源 id=%s size=%s md5=%s" %
                  (src["id"], src.get("size"), src.get("md5Checksum")))
            if dst is not None:
                print("      備份 id=%s size=%s md5=%s" %
                      (dst["id"], dst.get("size"), dst.get("md5Checksum")))
        if len(broken) > 40:
            print("  ... 其餘 %d 筆省略" % (len(broken) - 40))

    print("\nRESULT: %s" % ("ALL_FILES_OK 沒有發現壞檔" if not broken
                            else "BROKEN_FILES_FOUND 共 %d 個檔案有問題" % len(broken)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
