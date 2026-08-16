#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_images.py — 批量并发下载 QQ 群消息合并转发中的图片

从同目录 urls.txt 读取图片下载链接（每行一个），使用 ThreadPoolExecutor 并发下载，
按 urls.txt 中的原始顺序保存到 ./images/image_001.jpg ~ image_121.jpg。

特性：
- 16 个并发 worker（ThreadPoolExecutor）
- 每请求超时 30 秒，网络类错误自动重试最多 3 次（带 1s/2s 退避）
- 下载后校验魔数（JPEG/PNG/GIF/WebP/BMP），非图片内容（HTML/JSON 等）判失败
- 退出码：全部成功 0，存在失败 1
"""

import os
import sys
import json
import time
import gzip
import threading
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
URLS_FILE = os.path.join(BASE_DIR, "urls.txt")
IMAGES_DIR = os.path.join(BASE_DIR, "images")

WORKERS = 16          # 并发下载数
TIMEOUT = 30          # 单请求超时（秒）
MAX_ATTEMPTS = 3      # 最多尝试 3 次（首次 + 2 次重试）
RETRY_BACKOFF = (1.0, 2.0)  # 每次重试前的退避秒数

# QQ 多媒体下载接口通常校验 UA / Referer，带上浏览器 UA 提高成功率
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "Referer": "https://qun.qq.com/",
    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
}


def sniff_image_type(data: bytes):
    """按魔数识别图片类型；无法识别返回 None。"""
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data[:2] == b"BM":
        return "bmp"
    return None


def looks_like_error_page(data: bytes) -> bool:
    """粗判响应是否为 HTML / JSON 等非图片文本内容。"""
    head = data[:512].lstrip().lower()
    return head.startswith(b"<") or head.startswith(b"{") or head.startswith(b"[")


def download_one(url: str, index: int):
    """下载单个 URL 并保存为 image_{index+1:03d}.jpg，返回 (index, ok, reason)。"""
    path = os.path.join(IMAGES_DIR, f"image_{index + 1:03d}.jpg")
    last_err = None

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                status = getattr(resp, "status", None) or resp.getcode()
                if status != 200:
                    return (index, False, f"HTTP {status}")
                data = resp.read()
                enc = (resp.headers.get("Content-Encoding") or "").lower()
                if enc == "gzip":
                    try:
                        data = gzip.decompress(data)
                    except Exception:
                        pass  # 解压失败则按原字节做魔数校验

            img_type = sniff_image_type(data)
            if img_type is None:
                if looks_like_error_page(data):
                    return (index, False, "非图片内容(HTML/JSON等)")
                return (index, False, "魔数校验失败，非有效图片")
            if not data:
                return (index, False, "空文件")

            # 统一按 image_XXX.jpg 命名（实际格式见 reason 中的 img_type）
            with open(path, "wb") as f:
                f.write(data)
            return (index, True, f"ok({img_type})")

        except urllib.error.HTTPError as e:
            # 尝试解析错误体（QQ 多媒体接口返回 JSON，含 retmsg 原因）
            detail = ""
            try:
                body = e.read(512)
                text = body.decode("utf-8", errors="replace").strip()
                if text.startswith("{"):
                    detail = json.loads(text).get("retmsg") or ""
                elif text.startswith("<"):
                    detail = "HTML错误页"
                else:
                    detail = text[:80]
            except Exception:
                pass
            reason = f"HTTP {e.code}"
            if detail:
                reason += f" ({detail})"
            # 4xx 为明确拒绝，重试无意义；5xx 视为临时故障，走退避重试
            if 500 <= e.code < 600:
                last_err = reason
                if attempt < MAX_ATTEMPTS:
                    time.sleep(RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)])
                continue
            return (index, False, reason)

        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)])

    return (index, False, last_err)


def main():
    if not os.path.isfile(URLS_FILE):
        print(f"[错误] 找不到 {URLS_FILE}", file=sys.stderr)
        sys.exit(2)

    with open(URLS_FILE, "r", encoding="utf-8") as f:
        urls = [line.strip() for line in f if line.strip()]

    print(f"[信息] 读取到 {len(urls)} 条 URL，保存目录 {IMAGES_DIR}")
    os.makedirs(IMAGES_DIR, exist_ok=True)

    start = time.perf_counter()
    done = 0
    lock = threading.Lock()
    failures = []

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(download_one, url, i): i for i, url in enumerate(urls)}
        for fut in as_completed(futures):
            try:
                index, ok, reason = fut.result()
            except Exception as e:  # worker 内部未预期异常
                index, ok, reason = futures[fut], False, f"异常: {e}"
            with lock:
                done += 1
                if not ok:
                    failures.append((index, reason))
                if done % 20 == 0 or done == len(urls):
                    print(f"[进度] {done}/{len(urls)}")

    elapsed = time.perf_counter() - start
    success = len(urls) - len(failures)

    print("\n" + "=" * 60)
    print("下载统计：")
    print(f"  总数   : {len(urls)}")
    print(f"  成功   : {success}")
    print(f"  失败   : {len(failures)}")
    print(f"  总耗时 : {elapsed:.2f} 秒")
    if failures:
        shown = min(10, len(failures))
        print(f"  失败明细（前 {shown} 条）:")
        for idx, reason in failures[:shown]:
            print(f"    image_{idx + 1:03d}.jpg  <-  {urls[idx]}")
            print(f"      原因: {reason}")
    print("=" * 60)

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
