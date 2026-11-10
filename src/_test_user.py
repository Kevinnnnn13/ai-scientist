# -*- coding: utf-8 -*-
"""_test_user.py：多用户历史存储离线自测（不联网、不碰真实 users 目录）"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import user_store  # noqa: E402

# 重定向到临时目录，避免污染真实用户数据
user_store.USERS_ROOT = os.path.join(tempfile.mkdtemp(prefix="us_test_"), "users")


def main():
    # 1) 用户名校验
    cases = [
        ("张三", True), ("zhang_san", True), ("Alice-2026", True),
        ("", False), ("a/b", False), ("..", False), ("a b", False),
        ("a.b", False), ("a\\b", False), ("a" * 40, False),
    ]
    for name, expect in cases:
        ok, _u, err = user_store.sanitize_username(name)
        assert ok == expect, "sanitize(%r) 期望 %s 实际 %s (%s)" % (name, expect, ok, err)
    print("[PASS] 用户名校验 10 组（含路径穿越字符拦截）")

    # 2) 记录新增/更新/隔离
    user_store.ensure_user("alice")
    user_store.ensure_user("bob")
    user_store.upsert_run("alice", {"run_id": "r1", "question": "Q1", "status": "running", "started": 100})
    user_store.upsert_run("alice", {"run_id": "r1", "status": "done", "best_score": 88, "folder": "/tmp/nonexist"})
    user_store.upsert_run("bob", {"run_id": "r2", "question": "Q2", "status": "running", "started": 200})

    alice = user_store.list_history("alice")
    bob = user_store.list_history("bob")
    assert len(alice) == 1 and alice[0]["status"] == "done" and alice[0]["best_score"] == 88
    assert len(bob) == 1 and bob[0]["run_id"] == "r2"
    assert user_store.get_record("alice", "r1")["status"] == "done"
    assert user_store.get_record("alice", "r2") is None  # 跨用户隔离
    print("[PASS] upsert 更新/新增、用户间历史隔离")

    # 3) get_detail：文件夹不存在时返回记录本身（不抛错）
    d = user_store.get_detail("alice", "r1")
    assert d and d["run_id"] == "r1" and d["status"] == "done"
    print("[PASS] get_detail 兜底（结果文件夹不存在不崩溃）")

    # 4) 历史排序（新的在前）
    user_store.upsert_run("alice", {"run_id": "r0", "question": "Q0", "status": "done", "started": 300})
    top = user_store.list_history("alice", limit=10)
    assert top[0]["run_id"] == "r0"  # started=300 最新
    print("[PASS] 历史按时间倒序")

    print("\n结果：user_store 全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
