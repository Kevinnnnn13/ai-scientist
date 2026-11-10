# -*- coding: utf-8 -*-
"""MinerU 客户端自测：离线（token 缺失 + 网络失败回退路径）+ 可选真实上传。

用法：
  python src/_test_mineru.py                        # 离线自测
  python src/_test_mineru.py --real [pdf路径]        # 真实上传（默认 test_papers/paper3.pdf）
"""
import os
import sys


def test_offline():
    import mineru_client
    orig_token = mineru_client.get_token
    # 1) 无 token -> 快速失败（不联网）
    mineru_client.get_token = lambda: ""
    r = mineru_client.extract_pdf_markdown(b"x", "a.pdf", max_wait=1)
    assert r.get("error") and "未配置" in r["error"], r
    print("offline[1] 无 token 快速失败 OK")
    mineru_client.get_token = orig_token
    # 2) 申请上传网络失败 -> 返回 error（fail-open，调用方回退本地）
    orig_post = mineru_client._post_json
    def boom(*a, **k):
        raise RuntimeError("mock network down")
    mineru_client._post_json = boom
    r2 = mineru_client.extract_pdf_markdown(b"x", "a.pdf", max_wait=1)
    mineru_client._post_json = orig_post
    assert r2.get("error") and "申请上传失败" in r2["error"], r2
    print("offline[2] 网络失败回退 OK:", r2["error"][:60])
    # 3) token 存在性
    t = mineru_client.get_token()
    print("offline[3] MINERU_API_TOKEN %s" % ("已配置（长度 %d）" % len(t) if t else "未配置"))
    print("OFFLINE OK")


def test_real(pdf_path):
    import mineru_client
    raw = open(pdf_path, "rb").read()
    print("上传 %s（%d 字节）…" % (os.path.basename(pdf_path), len(raw)))
    r = mineru_client.extract_pdf_markdown(raw, os.path.basename(pdf_path))
    if r.get("error"):
        print("REAL FAIL:", r["error"])
        return 1
    text = r.get("text", "")
    print("REAL OK chars=%d" % len(text))
    print("预览:", repr(text[:300]))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    test_offline()
    if "--real" in sys.argv:
        i = sys.argv.index("--real")
        p = sys.argv[i + 1] if i + 1 < len(sys.argv) else os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "test_papers", "paper3.pdf"))
        sys.exit(test_real(os.path.abspath(p)))
