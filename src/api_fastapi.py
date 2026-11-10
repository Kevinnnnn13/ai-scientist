# -*- coding: utf-8 -*-
"""AI Scientist 可调用测试 API（FastAPI 版）。

用法：
  python src\\api_fastapi.py                # 启动，默认 127.0.0.1:8000
  python src\\api_fastapi.py --port 9000
  python -m uvicorn src.api_fastapi:app --host 0.0.0.0 --port 8000

与 src\\api_server.py 的关系：
  - 只替换 HTTP 服务器层（路由/请求解析/响应序列化/CORS/静态文件），
    URL 与 JSON 契约完全一致，web\\index.html 前端零改动；
  - 业务逻辑全部复用 api_server.py（start_run / run_status / 安全护栏 /
    追问闸门 / 文档解析 / 多用户 / 画像），共享同一份 RUNS 运行状态；
  - 启动后访问 /docs 可查看并在线测试全部接口（Swagger UI）。

接口清单（与 api_server.py 一致）：
  POST /api/run                    启动运行（含安全护栏/追问闸门）
  GET  /api/run/{run_id}           轮询状态/进度/分数/假设
  GET  /api/runs                   最近运行列表
  POST /api/run/{run_id}/feedback  写入人工反馈
  GET  /api/run/{run_id}/feedback  读取人工反馈
  GET  /api/run/{run_id}/export    导出结果报告（md/html）
  POST /api/login                  登录/游客
  GET  /api/history                历史列表
  GET  /api/history/{run_id}       历史详情
  GET  /api/history/{run_id}/export 历史导出
  GET  /api/profile                用户画像
  POST /api/parse_doc              论文文档解析（md/docx/pdf，云端 MinerU 优先）
  POST /api/translate              问题翻译
  GET  /api/mock                   联调假数据
  /                                静态前端（web/index.html）
"""
import base64
import os
import sys
from contextlib import asynccontextmanager
from typing import Optional
from urllib.parse import quote

import uvicorn
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ---- 复用 api_server.py 的全部业务逻辑（共享同一份 RUNS 状态） ----
import api_server as sv

SRC = sv.SRC


@asynccontextmanager
async def lifespan(app):
    """服务重启后接管遗留的 running 任务（与 api_server.main 行为一致）。"""
    sv._load_runs()
    for rid, info in list(sv.RUNS.items()):
        if info.get("status") == "running":
            sv._resume_watch(rid, info)
    yield


app = FastAPI(
    title="AI Scientist 科研假设生成系统 API",
    description=(
        "输入科学问题（可附论文）→ 安全护栏 → 追问精修 → 知识整合（知识树）→ "
        "缺口分析 → 假设生成 → 四维评审迭代 → 可验证性求证。"
        "本页面为 Swagger 自动生成，可在线测试全部接口。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS：与 api_server.py 的 Access-Control-Allow-Origin: * 一致
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(HTTPException)
async def _http_error(request, exc):
    """错误响应保持 {"error": ...} 格式，与 api_server.py 完全一致（前端 api() 读取 j.error）。"""
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


# ---- 请求模型 ----
class RunRequest(BaseModel):
    question: str = ""
    quality: str = "超好"
    papers: list = Field(default_factory=list)
    username: str = ""
    skip_clarify: bool = False
    clarify: Optional[list] = None


class LoginRequest(BaseModel):
    username: str = ""


class ParseDocRequest(BaseModel):
    name: str = ""
    data: str = ""


class TranslateRequest(BaseModel):
    text: str = ""


class FeedbackRequest(BaseModel):
    verdict: str = "未评价"
    questions: list = Field(default_factory=list)
    suggestions: list = Field(default_factory=list)


# ---- 工具函数 ----
def _guard_payload(guard):
    return {k: guard.get(k) for k in ("checked_by", "verdict", "categories", "risk", "reason")}


def _export_response(run_id, folder, fmt):
    sys.path.insert(0, SRC)
    import export_result as er
    d = er.collect(folder, with_plot=True)
    if fmt == "md":
        text, ext, mime = er.render_md(d), "md", "text/markdown; charset=utf-8"
    else:
        text, ext, mime = er.render_html(d), "html", "text/html; charset=utf-8"
    return Response(
        content=text.encode("utf-8"),
        media_type=mime,
        headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote("结果报告_%s.%s" % (run_id, ext))},
    )


# ---- 接口 ----
@app.get("/api/mock")
def api_mock(state: str = Query("done")):
    return sv._mock_run(state)


@app.get("/api/runs")
def api_runs():
    items = sorted(sv.RUNS.items(), key=lambda kv: kv[1].get("started", 0), reverse=True)[:20]
    return {"runs": [{"run_id": k, "question": v.get("question"), "status": v.get("status"),
                      "best_score": v.get("best_score")} for k, v in items]}


@app.get("/api/run/{run_id}")
def api_run_status(run_id: str):
    st = sv.run_status(run_id)
    return st if st else {"error": "run not found"}


@app.get("/api/run/{run_id}/export")
def api_run_export(run_id: str, fmt: str = Query("html")):
    folder = sv.RUNS.get(run_id, {}).get("folder")
    if not folder:
        raise HTTPException(404, "任务还未完成或没有结果目录，请等运行结束后再导出")
    return _export_response(run_id, folder, fmt)


@app.get("/api/run/{run_id}/feedback")
def api_get_feedback(run_id: str):
    folder = sv.RUNS.get(run_id, {}).get("folder")
    if not folder:
        raise HTTPException(404, "no folder")
    sys.path.insert(0, SRC)
    import human_loop
    return {"feedback": human_loop.load_feedback(folder)}


@app.post("/api/run/{run_id}/feedback")
def api_post_feedback(run_id: str, req: FeedbackRequest):
    folder = sv.RUNS.get(run_id, {}).get("folder")
    if not folder:
        raise HTTPException(404, "no folder")
    sys.path.insert(0, SRC)
    import human_loop
    fb = human_loop.empty_feedback()
    fb["verdict"] = req.verdict
    fb["questions"] = req.questions or []
    fb["suggestions"] = req.suggestions or []
    return {"saved": human_loop.save_feedback(folder, fb)}


@app.post("/api/login")
def api_login(req: LoginRequest):
    ok_u, username, err_u = sv._login_user((req.username or "").strip())
    if not ok_u:
        raise HTTPException(400, err_u)
    sys.path.insert(0, SRC)
    import user_store
    return {"ok": True, "username": username, "history": user_store.list_history(username)}


@app.get("/api/history")
def api_history(user: str = Query("")):
    ok_u, username, err_u = sv._login_user(user)
    if not ok_u:
        raise HTTPException(400, err_u)
    sys.path.insert(0, SRC)
    import user_store
    return {"username": username, "history": user_store.list_history(username)}


@app.get("/api/history/{run_id}")
def api_history_detail(run_id: str, user: str = Query("")):
    ok_u, username, err_u = sv._login_user(user)
    if not ok_u:
        raise HTTPException(400, err_u)
    sys.path.insert(0, SRC)
    import user_store
    detail = user_store.get_detail(username, run_id)
    if not detail:
        raise HTTPException(404, "记录不存在")
    return detail


@app.get("/api/history/{run_id}/export")
def api_history_export(run_id: str, user: str = Query(""), fmt: str = Query("html")):
    ok_u, username, err_u = sv._login_user(user)
    if not ok_u:
        raise HTTPException(400, err_u)
    sys.path.insert(0, SRC)
    import user_store
    rec = user_store.get_record(username, run_id)
    folder = rec.get("folder") if rec else None
    if not folder or not os.path.isdir(folder):
        raise HTTPException(404, "该记录没有结果文件夹（可能已被清理）")
    return _export_response(run_id, folder, fmt)


@app.get("/api/profile")
def api_profile(user: str = Query("guest")):
    ok_u, username, err_u = sv._login_user(user)
    if not ok_u:
        raise HTTPException(400, err_u)
    sys.path.insert(0, SRC)
    import user_profile
    try:
        return user_profile.get_profile_for_api(username)
    except Exception as e:
        return {"ready": False, "reason": "画像服务异常：%s" % e,
                "profile": None, "backend": None, "updated_at": None}


@app.post("/api/parse_doc")
def api_parse_doc(req: ParseDocRequest):
    name = (req.name or "").strip()
    data_b64 = req.data or ""
    if not name or not data_b64:
        raise HTTPException(400, "name / data required")
    try:
        raw = base64.b64decode(data_b64)
    except Exception:
        raise HTTPException(400, "文件数据不是合法的 base64")
    res = sv.extract_doc_text(name, raw)
    if res.get("error"):
        raise HTTPException(400, res["error"])
    return {"name": name, "text": res.get("text", ""), "chars": res.get("chars", 0),
            "warning": res.get("warning", ""), "source": res.get("source", "")}


@app.post("/api/translate")
def api_translate(req: TranslateRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(400, "text required")
    try:
        sys.path.insert(0, SRC)
        import llm_client
        translated = llm_client.chat(
            "请把下面这段科学问题翻译成地道的英文科学提问。要求：保留专业术语；"
            "中文就译为英文，英文则轻微润色；直接输出翻译结果，不要任何解释、引号或额外内容。\n\n" + text,
            system="你是科研翻译助手，只输出翻译后的英文文本。"
        ).strip()
        return {"translated": translated, "source": text}
    except Exception as e:
        raise HTTPException(500, "翻译失败：" + str(e))


@app.post("/api/run")
def api_run(req: RunRequest):
    q = (req.question or "").strip()
    if not q:
        raise HTTPException(400, "question required")
    err = sv._deepseek_key_error()
    if err:
        raise HTTPException(400, err)
    running = sum(1 for v in sv.RUNS.values() if v.get("status") == "running")
    if running >= sv.MAX_CONCURRENT:
        raise HTTPException(429, "同时运行的任务已达 %d 个上限，请等当前任务完成后再试" % sv.MAX_CONCURRENT)
    papers = req.papers if isinstance(req.papers, list) else []
    papers = [str(x).strip() for x in papers if str(x).strip()][:3]
    username = (req.username or "").strip() or "guest"
    ok_u, username, err_u = sv._login_user(username)
    if not ok_u:
        raise HTTPException(400, err_u)

    # 输入安全护栏：先拦违规提问（防止把系统当危险品制作指南用）
    guard = sv._guard_check(q, papers)
    if not guard.get("allowed", True):
        return {"blocked": True, "guard": _guard_payload(guard)}

    # 追问精修闸门：白名单/清晰问题直接跑；模糊问题先返回 2-3 个追问
    skip_clarify = bool(req.skip_clarify)
    clarify = req.clarify
    if skip_clarify:
        clarify = []
    elif clarify is None:
        gate = sv._clarify_gate(q, papers)
        if gate.get("need_clarify"):
            return {"need_clarify": True, "questions": gate.get("questions", []),
                    "reason": gate.get("reason", "")}
        clarify = []
    if not isinstance(clarify, list):
        clarify = []
    clarify = [{"question": str(x.get("question") or "").strip(),
                "answer": str(x.get("answer") or "").strip()}
               for x in clarify if isinstance(x, dict) and str(x.get("answer") or "").strip()]

    # 追问回答与原问题合并后再过一遍安全护栏（防夹带违规/注入）
    if clarify:
        merged = sv._clarify_merge(q, clarify)
        guard2 = sv._guard_check(merged, papers)
        if not guard2.get("allowed", True):
            return {"blocked": True, "guard": _guard_payload(guard2)}
        guard = guard2

    rid = sv.start_run(q, req.quality, papers=papers, clarify=clarify, user=username)
    if rid in sv.RUNS:
        sv.RUNS[rid]["guard"] = _guard_payload(guard)
        sv.RUNS[rid]["clarify"] = clarify
        sv.RUNS[rid]["user"] = username
        sv._save_runs()
    return {"run_id": rid, "status": "started", "guard": _guard_payload(guard)}


# ---- 静态前端（与 api_server.py 的 web/ 托管一致） ----
WEB_DIR = os.path.normpath(os.path.join(SRC, "..", "web"))
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


def main():
    host = "127.0.0.1"
    port = 8000
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        port = int(sys.argv[i + 1])
    if "--host" in sys.argv:
        i = sys.argv.index("--host")
        host = sys.argv[i + 1]
    print(f"AI Scientist API (FastAPI) 已启动：http://{host}:{port}  （Ctrl+C 停止）")
    print(f"接口文档（Swagger UI）：http://{host}:{port}/docs")
    if host in ("0.0.0.0", "::"):
        try:
            import socket
            ips = socket.gethostbyname_ex(socket.gethostname())[2]
            lan = [x for x in ips if x.startswith(("192.168.", "10.", "172."))] or ips
            print("局域网访问：http://%s:%s  （同学在同一个 WiFi 下打开这个地址）" % (lan[0], port))
        except Exception:
            pass
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()
