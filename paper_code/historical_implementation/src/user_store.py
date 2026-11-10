# -*- coding: utf-8 -*-
"""user_store.py：多用户历史记忆（本地版）—— 用户名 → 各自的历史运行记录

背景：让评委/同学输入用户名登录，就能查看自己之前跑过的所有记录。
当前阶段无密码（后期加密码只改认证层，本模块只管「存/取历史」，接口不变）。

存储：users/<用户名>/records.json
  - 每条记录：{run_id, question, quality, started, status, best_score,
               best_data_score, folder, error_msg, clarify}
  - 用 RLock 防并发写（ThreadingHTTPServer 多线程）

安全：用户名白名单 [中英文数字_-]，长度 1-32，天然防路径穿越。
"""
import io
import json
import os
import re
import threading

SRC = os.path.dirname(os.path.abspath(__file__))
USERS_ROOT = os.path.join(SRC, "users")

_USERNAME_RE = re.compile(r"^[0-9A-Za-z_\-\u4e00-\u9fff]{1,32}$")
_lock = threading.RLock()
MAX_RECORDS = 200


def sanitize_username(name):
    """校验并归一化用户名。返回 (ok, username, error)。"""
    name = (name or "").strip()
    if not name:
        return False, "", "请输入用户名"
    if not _USERNAME_RE.match(name):
        return False, "", "用户名只能包含中文/字母/数字/下划线/连字符，长度 1-32 位"
    return True, name, ""


def _records_file(username):
    return os.path.join(USERS_ROOT, username, "records.json")


def ensure_user(username):
    """创建用户目录（不存在则建），返回目录路径。"""
    d = os.path.join(USERS_ROOT, username)
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    return d


def load_records(username):
    with _lock:
        fp = _records_file(username)
        try:
            with io.open(fp, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []


def _save_locked(username, records):
    fp = _records_file(username)
    try:
        with io.open(fp, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def upsert_run(username, rec):
    """按 run_id 新增/更新一条记录（运行中先记一条，结束后更新状态分数）。"""
    if not rec or not rec.get("run_id"):
        return
    with _lock:
        records = load_records(username)
        for i, r in enumerate(records):
            if r.get("run_id") == rec.get("run_id"):
                merged = dict(r)
                merged.update({k: v for k, v in rec.items() if v is not None})
                records[i] = merged
                _save_locked(username, records)
                return
        records.insert(0, rec)
        records = records[:MAX_RECORDS]
        _save_locked(username, records)


def list_history(username, limit=50):
    """历史列表（新的在前）。软删除（2026-08-30）：deleted=True 的记录对用户隐藏，
    但数据保留在磁盘（供安全审计 / 用户行为分析 / 未来知识图谱使用，绝不进入任何用户可见输出）。"""
    records = load_records(username)
    records = [r for r in records if not r.get("deleted")]
    records = sorted(records, key=lambda r: r.get("started") or 0, reverse=True)
    return records[:limit]


def get_record(username, run_id, include_deleted=False):
    for r in load_records(username):
        if r.get("run_id") == run_id:
            if not include_deleted and r.get("deleted"):
                return None
            return r
    return None


def delete_record(username, run_id):
    """软删除一条历史（标记 deleted=True，不物理删除）。
    设计（2026-08-30，用户拍板）：用户视角「删了就是删了」（列表/详情/画像均排除），
    但原始数据保留供审计与分析——尤其被安全护栏拦截的违规请求记录不能真删。"""
    with _lock:
        records = load_records(username)
        changed = False
        for r in records:
            if r.get("run_id") == run_id and not r.get("deleted"):
                r["deleted"] = True
                changed = True
        if changed:
            _save_locked(username, records)
        return changed


def tree_for_frontend(st):
    """把 state.knowledge_tree 精简成前端可渲染形态（去掉大段摘要，留标题/链接/短摘要）。"""
    kt = st.get("knowledge_tree")
    if not isinstance(kt, dict):
        return None
    subs = []
    for sp in kt.get("sub_problems") or []:
        if not isinstance(sp, dict):
            continue
        papers = []
        for p in sp.get("papers") or []:
            if isinstance(p, dict):
                papers.append({
                    "标题": str(p.get("标题") or "").strip(),
                    "链接": str(p.get("链接") or "").strip(),
                    "摘要": (str(p.get("摘要") or "").strip())[:200],
                })
        cov = str(sp.get("coverage") or "").strip() or ("gap" if not papers else "covered")
        subs.append({
            "id": sp.get("id"),
            "name": str(sp.get("name") or "").strip(),
            "concepts": sp.get("concepts") or [],
            "verifiable_angles": sp.get("verifiable_angles") or [],
            "open_debate": bool(sp.get("open_debate")),
            "coverage": cov,
            "papers": papers,
        })
    return {
        "root_question": str(kt.get("root_question") or "").strip(),
        "analysis": str(kt.get("analysis") or "").strip(),
        "sub_problems": subs,
    }


def get_detail(username, run_id):
    """读取某次运行的最终详情（从结果文件夹 state.json 回读），与 run_status 的 done 形态一致。"""
    rec = get_record(username, run_id)
    if not rec:
        return None
    out = dict(rec)
    folder = rec.get("folder")
    if folder and os.path.isdir(folder):
        sj = os.path.join(folder, "state.json")
        if os.path.isfile(sj):
            try:
                with io.open(sj, encoding="utf-8") as f:
                    st = json.load(f)
                if st.get("error"):
                    out["status"] = "error"
                    out["error_msg"] = str(st["error"])[:800]
                else:
                    out["status"] = "done"
                    out["best_score"] = st.get("best_score")
                    out["best_data_score"] = st.get("best_data_score")
                    out["rounds"] = len(st.get("score_history") or [])
                    out["hypothesis"] = (st.get("best_hypothesis") or st.get("hypothesis") or "")[:4000]
                    out["plan_status"] = st.get("plan_status")
                    out["evidence_status"] = st.get("evidence_status")
                    out["final_answer"] = str(st.get("final_answer") or "")[:6000]
                    out["cost_cny"] = st.get("api_cost_cny")
                    out["api_usage"] = st.get("api_usage")
                    out["knowledge_tree"] = tree_for_frontend(st)
                    out["knowledge_gaps"] = st.get("knowledge_gaps") or []
            except Exception:
                pass
    return out


if __name__ == "__main__":
    print("user_store 模块：OK")
