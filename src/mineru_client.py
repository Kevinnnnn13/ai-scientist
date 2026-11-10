# -*- coding: utf-8 -*-
"""MinerU 云端文档解析客户端（2026-08-28 新增）。

把 PDF / DOCX 等上传到 mineru.net 云端解析成 Markdown 文字，
解决扫描版 PDF、公式乱码、复杂版式问题。
只用 Python 标准库；任何一步失败都返回 {"error": ...}，由调用方回退本地解析，不抛异常。

流程（MinerU v4 精准解析 API）：
  POST /api/v4/file-urls/batch    申请上传链接
  PUT  上传文件到返回的 url
  GET  /api/v4/extract/task/{batch_id}   轮询（pending/running/done/failed）
  done 后下载 full_zip_url，解出 full.md 返回

配额提醒：Token 有效期约 3 个月（2026-08-28 创建，约 2026-11-28 到期，需续期）；
每天免费 1000 页（超过部分降优先级），单文件 <=200MB / <=200 页。
"""
import io
import json
import os
import time
import urllib.request
import zipfile

API_BASE = "https://mineru.net/api/v4"
DEFAULT_TIMEOUT = 30      # 单次 HTTP 请求超时（秒）
UPLOAD_TIMEOUT = 180      # PUT 上传超时（秒）
POLL_INTERVAL = 3         # 轮询间隔（秒）
MAX_POLL_SECONDS = 300    # 云端解析总等待上限（秒）


def get_token():
    """读取 .env 里的 MINERU_API_TOKEN；未配置返回空串。"""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass
    return (os.getenv("MINERU_API_TOKEN") or "").strip()


def _post_json(url, payload, headers, timeout=DEFAULT_TIMEOUT):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _get_json(url, headers, timeout=DEFAULT_TIMEOUT):
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _upload(url, raw, timeout=UPLOAD_TIMEOUT):
    """PUT 上传文件内容（OSS 签名 URL）。

    注意：必须用 http.client 而非 urllib——urllib 会给 PUT 自动补
    Content-Type: application/x-www-form-urlencoded，OSS 对请求头签名校验会 403。
    文档要求上传时无须设置 Content-Type，只带 Content-Length 即可。
    """
    from http.client import HTTPSConnection, HTTPConnection
    from urllib.parse import urlsplit
    u = urlsplit(url)
    conn = (HTTPSConnection if u.scheme == "https" else HTTPConnection)(u.netloc, timeout=timeout)
    try:
        path = u.path + (("?" + u.query) if u.query else "")
        conn.putrequest("PUT", path)
        conn.putheader("Content-Length", str(len(raw)))
        conn.endheaders()
        conn.send(raw)
        resp = conn.getresponse()
        body = resp.read()
        if resp.status not in (200, 201, 204):
            raise RuntimeError("HTTP %s %s" % (resp.status, body[:200].decode("utf-8", errors="replace")))
    finally:
        conn.close()


def _auth(token):
    return {"Authorization": "Bearer " + token}


def _find_full_zip_url(data):
    """兼容单文件/批量两种返回结构。"""
    if data.get("full_zip_url"):
        return data["full_zip_url"]
    for it in data.get("extract_result") or []:
        if isinstance(it, dict) and it.get("full_zip_url"):
            return it["full_zip_url"]
    return None


def _download_and_read_md(zip_url, timeout=DEFAULT_TIMEOUT):
    """下载结果 zip，内存里解出 full.md 文字。"""
    req = urllib.request.Request(zip_url, method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    zf = zipfile.ZipFile(io.BytesIO(data))
    target = None
    for n in zf.namelist():
        if n.endswith("full.md"):
            target = n
            break
    if not target:
        return {"error": "MinerU 结果包中未找到 full.md"}
    text = zf.read(target).decode("utf-8", errors="replace")
    return {"text": text}


def _batch_state(d):
    """批量结果状态判定：兼容顶层 state 与 extract_result 数组两种结构。"""
    st = d.get("state")
    if st in ("done", "failed", "running", "pending", "converting"):
        return st
    er = d.get("extract_result") or []
    if not er:
        return "running"
    fail = [x for x in er if isinstance(x, dict) and (x.get("code") not in (0, None) or x.get("err_msg"))]
    if fail:
        return "failed"
    if all(isinstance(x, dict) and x.get("full_zip_url") for x in er):
        return "done"
    return "running"


def _batch_err(d):
    for x in d.get("extract_result") or []:
        if isinstance(x, dict) and x.get("err_msg"):
            return x["err_msg"]
    return d.get("err_msg") or "未知原因"


def extract_pdf_markdown(raw, name="paper.pdf", max_wait=MAX_POLL_SECONDS):
    """上传文件到 MinerU 云端解析，返回 {"text": str} 或 {"error": str}。

    失败（网络/配额/超时）一律返回 error，由调用方回退本地解析。
    """
    token = get_token()
    if not token:
        return {"error": "MINERU_API_TOKEN 未配置，跳过云端解析"}
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + token}
    # 1) 申请上传链接（批量接口，单文件也走它）
    try:
        resp = _post_json(API_BASE + "/file-urls/batch",
                          {"files": [{"name": name}], "model_version": "vlm"}, headers)
    except Exception as e:
        return {"error": "MinerU 申请上传失败：%s" % e}
    if resp.get("code") != 0:
        return {"error": "MinerU 申请上传被拒：%s" % (resp.get("msg") or resp)}
    data = resp.get("data") or {}
    batch_id = data.get("batch_id")
    urls = data.get("file_urls") or []
    if not batch_id or not urls:
        return {"error": "MinerU 返回缺少 batch_id / file_urls"}
    # 2) PUT 上传
    try:
        _upload(urls[0], raw)
    except Exception as e:
        return {"error": "MinerU 上传失败：%s" % e}
    # 3) 轮询解析结果：批量端点优先（upload 流程），单文件端点兜底
    url_batch = API_BASE + "/extract-results/batch/" + batch_id
    url_single = API_BASE + "/extract/task/" + batch_id
    deadline = time.time() + max_wait
    while time.time() < deadline:
        d = None
        for url in (url_batch, url_single):
            try:
                r = _get_json(url, _auth(token))
            except Exception:
                continue
            if r.get("code") == 0 and r.get("data"):
                d = r.get("data") or {}
                break
        if d is None:
            time.sleep(POLL_INTERVAL)
            continue
        state = _batch_state(d)
        if state == "done":
            zip_url = _find_full_zip_url(d)
            if not zip_url:
                return {"error": "MinerU 解析完成但缺少结果下载地址"}
            try:
                return _download_and_read_md(zip_url)
            except Exception as e:
                return {"error": "MinerU 结果下载失败：%s" % e}
        if state == "failed":
            return {"error": "MinerU 解析失败：%s" % _batch_err(d)}
        time.sleep(POLL_INTERVAL)
    return {"error": "MinerU 云端解析超时（%d 秒）" % max_wait}
