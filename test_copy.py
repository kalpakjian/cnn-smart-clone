#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""測試: 在目前 OAuth 權限 (drive.file) 下, 伺服器端 files.copy 能否複製共用來源檔案的內容。

只做一次實驗: 複製 -> 檢查大小/md5 -> 刪除測試檔。不影響既有備份。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backup_cnn_drive as b  # noqa: E402

SRC_FILE_ID = "1KdoF_z0W4BsA4jKJCMNK1s8uNVxakehX"  # 3 IVDC OpenCV.pdf
SRC_MD5 = "87c880dc1c477b2f74c61bbd6ab693e6"
SRC_SIZE = 1597203


def main():
    dst_root, _ = b.find_or_create_target()
    print("目的地資料夾: %s" % dst_root)

    print("\n[1] 嘗試 POST /files/%s/copy ..." % SRC_FILE_ID)
    try:
        made = b.api("POST", "/files/%s/copy" % SRC_FILE_ID,
                     {"fields": "id,name,size,md5Checksum,mimeType"},
                     {"name": "__copy_test__.pdf", "parents": [dst_root]})
    except Exception as exc:
        print("  ❌ files.copy 失敗: %s" % exc)
        return 1

    print("  ✅ files.copy 成功: id=%s name=%s size=%s md5=%s mime=%s"
          % (made.get("id"), made.get("name"), made.get("size"),
             made.get("md5Checksum"), made.get("mimeType")))
    ok = (str(made.get("size")) == str(SRC_SIZE)
          and made.get("md5Checksum") == SRC_MD5)
    print("  內容正確? %s (期望 size=%d md5=%s)"
          % ("是 ✅" if ok else "否 ❌", SRC_SIZE, SRC_MD5))

    print("\n[2] 刪除測試檔 ...")
    b.api("DELETE", "/files/" + made["id"])
    print("  已刪除")
    return 0


if __name__ == "__main__":
    sys.exit(main())
