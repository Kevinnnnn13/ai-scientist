# -*- coding: utf-8 -*-
"""AI Scientist 可调用测试 API（零依赖，Python 标准库实现）。

用法：
  python src\api_server.py            # 启动，默认 127.0.0.1:8000
  python src\api_server.py --port 9000

接口（REST / JSON）：
  POST /api/run                {"question": "...", "quality": "好|超好"}  -> 启动运行，返回 run_id
  GET  /api/run/{run_id}       -> 运行状态/分数/假设（running 或最终结果）
  GET  /api/runs               -> 最近运行列表
  POST /api/run/{run_id}/feedback {"verdict","questions","suggestions"}   -> 写入人工反馈
  GET  /api/run/{run_id}/feedback

说明：运行通过子进程调用 langgraph_agent.py，与批处理互不影响；
设计为 REST 风格，部署时可平移到 FastAPI（接口不变）。
"""
import base64
import io
import json
import os
import re
import sys
import time
import uuid
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs, quote

SRC = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))
AGENT = os.path.join(SRC, "langgraph_agent.py")
LOG_DIR = os.path.join(SRC, "logs")
RUNS_DIR = os.path.join(SRC, "api_runs.json")
QUALITY_MAP = {"好": "好", "80": "好", "超好": "超好", "90": "超好", "顶级": "顶级", "92": "顶级", "一般": "一般", "70": "一般"}
MAX_CONCURRENT = 2  # 同时运行的子进程上限（2026-08-30：服务器 2C2G 内存吃紧，限 2 道；后期升级配置后可调回 3）
_MIME = {
    ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".mjs": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif",
    ".ico": "image/x-icon", ".webp": "image/webp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf", ".otf": "font/otf",
    ".txt": "text/plain; charset=utf-8", ".md": "text/markdown; charset=utf-8", ".map": "application/json",
}
if getattr(sys, "frozen", False):
    WEB_DIR = os.path.join(getattr(sys, "_MEIPASS", SRC), "web")
else:
    WEB_DIR = os.path.normpath(os.path.join(SRC, "..", "web"))

RUNS = {}  # run_id -> info


def _pid_alive(pid):
    """Windows 下可靠地判断进程是否存活（os.kill(pid,0) 在 Windows 语义不可靠）。"""
    if not pid:
        return False
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        return True  # 不确定时保守保留


def _load_runs():
    global RUNS
    try:
        with open(RUNS_DIR, encoding="utf-8") as f:
            loaded = json.load(f)
    except Exception:
        loaded = {}
    RUNS = {}
    for k, v in (loaded or {}).items():
        # 上次会话遗留的孤儿运行（进程已死但标记 running）直接丢弃，避免永远“运行中”
        if v.get("status") == "running" and not _pid_alive(v.get("pid")):
            continue
        RUNS[k] = v
    _save_runs()


def _save_runs():
    try:
        with open(RUNS_DIR, "w", encoding="utf-8") as f:
            json.dump(RUNS, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _deepseek_key_error():
    """校验 DeepSeek Key：缺失 / 模板占位 / 含非 ASCII 返回错误信息；正常返回 None。"""
    try:
        from dotenv import load_dotenv
        if getattr(sys, "frozen", False):
            load_dotenv(os.path.join(SRC, ".env"))
        else:
            load_dotenv()
    except Exception:
        pass
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        return "未检测到 DEEPSEEK_API_KEY：请编辑 exe 同目录的 .env 文件，填入 platform.deepseek.com 获取的 Key（形如 sk-xxxx）后重启程序。"
    if not key.startswith("sk-") or "填入" in key or "REPLACE" in key:
        return "DEEPSEEK_API_KEY 仍是模板占位符：请编辑 exe 同目录的 .env 文件，填入真实 Key 后重启程序。"
    try:
        key.encode("ascii")
    except UnicodeEncodeError:
        return "DEEPSEEK_API_KEY 含有非 ASCII 字符（可能是模板占位符）：请填写真实 Key。"
    return None


def _guard_check(question, papers=None):
    """输入安全护栏（失败放行）：调用 safety_guard.check_question。
    规则层命中直接拦截；LLM 裁判异常时 fail-open，避免护栏故障误伤正常提问。"""
    try:
        sys.path.insert(0, SRC)
        import safety_guard
        return safety_guard.check_question(question, papers)
    except Exception as e:
        print("[guard] 安全护栏异常，放行：%s" % e)
        return {"allowed": True, "checked_by": "error", "verdict": "safe",
                "categories": ["none"], "risk": "low", "reason": "安全护栏异常，已放行", "force_llm": False}


def _clarify_gate(question, papers=None):
    """追问判断闸门（失败放行，不追问）：白名单/清晰问题直接跑。"""
    try:
        sys.path.insert(0, SRC)
        import clarify
        return clarify.needs_clarification(question, papers)
    except Exception as e:
        print("[clarify] 追问判断异常，走快通道：%s" % e)
        return {"need_clarify": False, "questions": [], "reason": "追问判断异常，走快通道"}


def _clarify_merge(question, qa):
    """把原始问题 + 追问 Q&A 合并成精修上下文（安全复查与喂给主流程共用）。"""
    try:
        sys.path.insert(0, SRC)
        import clarify
        return clarify.merge_clarification(question, qa)
    except Exception:
        return question


def _login_user(name):
    """校验用户名并确保目录存在。返回 (ok, username, error)。"""
    try:
        sys.path.insert(0, SRC)
        import user_store
        ok, username, err = user_store.sanitize_username(name)
        if not ok:
            return False, "", err
        user_store.ensure_user(username)
        return True, username, ""
    except Exception as e:
        print("[user_store] 登录异常：%s" % e)
        return False, "", "用户系统异常：" + str(e)


def _sync_record(rid):
    """把 RUNS 里的最新状态同步进对应用户的历史记录。"""
    info = RUNS.get(rid)
    if not info:
        return
    user = info.get("user") or "guest"
    try:
        sys.path.insert(0, SRC)
        import user_store
        user_store.upsert_run(user, {
            "run_id": rid,
            "question": info.get("question"),
            "quality": info.get("quality"),
            "started": info.get("started"),
            "status": info.get("status"),
            "best_score": info.get("best_score"),
            "best_data_score": info.get("best_data_score"),
            "plan_status": info.get("plan_status"),
            "evidence_status": info.get("evidence_status"),
            "folder": info.get("folder"),
            "error_msg": (info.get("error_msg") or "")[:500],
        })
        # 同步后刷新用户画像的 Episode 数据（Zep 兼容格式，画像模块读取）
        try:
            import user_profile
            user_profile.refresh_episodes_file(user)
        except Exception:
            pass
    except Exception as e:
        print("[user_store] 记录同步失败：%s" % e)


def _mock_run(state):
    """前端联调用假数据：模拟不同运行状态，不消耗 token。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    base = {
        "run_id": "mock_" + state,
        "question": "What causes the 11-year solar cycle?",
        "quality": "超好",
        "status": state,
        "started": time.time() - 120,
        "rounds": 3,
        "progress": {"stage": "评审", "round": 3, "detail": "第 3 轮评审中（联调假数据）", "ts": now,
                     "tokens": 45210, "cost_cny": 0.0108, "prompt_tokens": 30000, "completion_tokens": 15210},
    }
    if state == "running":
        base["progress"] = {"stage": "假设生成", "round": 2,
                            "detail": "正在生成第 2 轮候选假设（联调假数据）", "ts": now,
                            "tokens": 21000, "cost_cny": 0.0050, "prompt_tokens": 14000, "completion_tokens": 7000}
    elif state == "finishing":
        base["progress"] = {"stage": "可验证性验证", "round": 3,
                            "detail": "运行结束，正在整理结果（联调假数据）", "ts": now,
                            "tokens": 45210, "cost_cny": 0.0108, "prompt_tokens": 30000, "completion_tokens": 15210}
    elif state == "error":
        base["status"] = "error"
        base["error_msg"] = "子进程提前退出，未生成结果。日志尾部：\n（联调假数据，正常情况请检查 .env 里的 Key）"
    else:  # done
        base["status"] = "done"
        base["best_score"] = 88
        base["best_data_score"] = 76
        base["hypothesis"] = ("**研究缺口**：关于太阳活动周的成因，现有发电机模型在极向磁场反转细节上仍缺乏统一解释。\n"
                              "**候选假设**：极向磁场反转的起始时间与日面低纬度差旋层径向剪切强度存在约 0.5 年的可观测滞后。\n"
                              "**验证方法**：利用 24 个太阳活动周的黑子磁场图与极向磁场时序做交叉相关分析。\n"
                              "（联调假数据，请以真实运行结果为准）")
        base["folder"] = "mock"
        base["cost_cny"] = 0.0108
        base["api_usage"] = {"prompt_tokens": 30000, "completion_tokens": 15210, "calls": 18}
    return base

def _tree_for_frontend(st):
    """复用 user_store 里的精简逻辑，把知识树交给前端。"""
    try:
        sys.path.insert(0, SRC)
        import user_store
        return user_store.tree_for_frontend(st)
    except Exception:
        return None


def _find_state_for_run(question, started_after):
    """运行结束后，在 27日/生成日志 找该题最新 state.json（按修改时间）。"""
    # 优先环境变量 AI_LOG_DIR（服务器部署统一数据目录）；否则回退本地默认路径
    _env_log = os.environ.get("AI_LOG_DIR", "").strip()
    if _env_log:
        base = _env_log
    elif getattr(sys, "frozen", False):
        base = os.path.join(SRC, "27日", "生成日志")
    else:
        base = os.path.join(os.path.expanduser("~"), "Desktop", "26暑假", "27日", "生成日志")
    if not os.path.isdir(base):
        return None
    best = None    # 精确匹配（题目一致）
    latest = None  # 兜底：题目不一致时取最近一次
    for day in os.listdir(base):
        daydir = os.path.join(base, day)
        if not os.path.isdir(daydir):
            continue
        for name in os.listdir(daydir):
            if not name.startswith("运行"):
                continue
            sj = os.path.join(daydir, name, "state.json")
            if not os.path.isfile(sj):
                continue
            try:
                mt = os.path.getmtime(sj)
            except Exception:
                continue
            if mt < started_after:
                continue
            try:
                with open(sj, encoding="utf-8") as f:
                    st = json.load(f)
            except Exception:
                continue
            if latest is None or mt > latest[0]:
                latest = (mt, sj, st)
            if str(st.get("question", "")).strip() == str(question).strip():
                if best is None or mt > best[0]:
                    best = (mt, sj, st)
    return best or latest
def extract_doc_text(name, raw):
    """本地提取文档文字：.md/.txt 直接读；.docx 解 word/document.xml；.pdf 用 pypdf。
    只做文字提取，不做联网 OCR（扫描版 PDF 会提示改传文本）。"""
    ext = os.path.splitext(name or "")[1].lower()
    try:
        if ext in (".md", ".markdown", ".txt"):
            text = raw.decode("utf-8", errors="replace")
            return {"text": text, "chars": len(text)}
        if ext == ".docx":
            import zipfile
            try:
                z = zipfile.ZipFile(io.BytesIO(raw))
                if "word/document.xml" not in z.namelist():
                    return {"error": "该 .docx 缺少正文内容，请确认文件完整或直接粘贴论文文字。"}
                xml = z.read("word/document.xml").decode("utf-8", errors="replace")
            except zipfile.BadZipFile:
                return {"error": "该 .docx 文件已损坏或不是有效的 Word 文档，请直接粘贴论文文字。"}
            xml = re.sub(r"</w:p>", "\n", xml)
            text = re.sub(r"<[^>]+>", "", xml)
            text = re.sub(r"[ \t]+", " ", text)
            text = "\n".join(ln.strip() for ln in text.splitlines() if ln.strip())
            return {"text": text, "chars": len(text)}
        if ext == ".pdf":
            # 云端优先：MinerU 精准解析（扫描版/公式/复杂版式更稳），失败自动回退本地 pypdf
            try:
                import mineru_client
                if mineru_client.get_token():
                    mr = mineru_client.extract_pdf_markdown(raw, name)
                    if not mr.get("error") and str(mr.get("text") or "").strip():
                        text = str(mr["text"]).strip()
                        return {"text": text, "chars": len(text), "source": "mineru"}
            except Exception:
                pass
            try:
                import pypdf
            except ImportError:
                return {"error": "当前程序未内置 PDF 解析库，无法读取 PDF。请改用 .md/.txt，或把论文文字直接粘贴进输入框。"}
            try:
                reader = pypdf.PdfReader(io.BytesIO(raw))
                if getattr(reader, "is_encrypted", False):
                    try:
                        reader.decrypt("")
                    except Exception:
                        return {"error": "该 PDF 已加密，无法读取文字。请先解除密码保护，或直接粘贴论文文字。"}
            except Exception as e:
                return {"error": "该 PDF 文件无法解析：%s。请改用 .md/.txt 或直接粘贴论文文字。" % e}
            pages = []
            for pg in reader.pages:
                try:
                    pages.append(pg.extract_text() or "")
                except Exception:
                    pages.append("")
            text = re.sub(r"\n{3,}", "\n\n", "\n".join(pages)).strip()
            if len(text.strip()) < 50:
                return {"text": text, "chars": len(text),
                        "warning": "该 PDF 可能是扫描版/图片版，未提取到足够文字，建议直接粘贴论文文字。"}
            return {"text": text, "chars": len(text)}
        return {"error": "不支持的文件类型：%s。仅支持 .md / .docx / .pdf" % (ext or "（无扩展名）")}
    except Exception as e:
        return {"error": "解析失败：%s" % e}


def start_run(question, quality, papers=None, clarify=None, user="guest", question_en=""):
    quality = QUALITY_MAP.get(str(quality), "超好")
    run_id = time.strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:4]
    log_path = os.path.join(LOG_DIR, f"api_{run_id}.log")
    os.makedirs(LOG_DIR, exist_ok=True)
    progress_path = os.path.join(LOG_DIR, f"api_{run_id}.progress.json")
    if os.path.isfile(progress_path):
        try:
            os.remove(progress_path)
        except Exception:
            pass
    logf = io.open(log_path, "a", encoding="utf-8", errors="replace")
    logf.write(f"题目：{question}\n目标：{quality}\n开始：{time.strftime('%H:%M:%S')}\n\n")
    if papers:
        logf.write("论文：" + str(len(papers)) + " 篇\n")
    if clarify:
        logf.write("追问补充：" + str(len(clarify)) + " 条\n")
    logf.flush()
    papers_path = None
    if papers:
        papers_path = os.path.join(LOG_DIR, f"api_{run_id}.papers.json")
        try:
            with io.open(papers_path, "w", encoding="utf-8") as f:
                json.dump(papers, f, ensure_ascii=False)
        except Exception:
            papers_path = None
    clarify_path = None
    if clarify:
        clarify_path = os.path.join(LOG_DIR, f"api_{run_id}.clarify.json")
        try:
            with io.open(clarify_path, "w", encoding="utf-8") as f:
                json.dump(clarify, f, ensure_ascii=False)
        except Exception:
            clarify_path = None
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PROGRESS_FILE"] = progress_path
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--worker", question, "--quality", quality]
        workdir = SRC
    else:
        cmd = [sys.executable, AGENT, question, "--quality", quality]
        workdir = os.path.dirname(SRC)
    if papers_path:
        cmd += ["--papers", papers_path]
    if clarify_path:
        cmd += ["--clarify", clarify_path]
    if question_en:
        cmd += ["--question-en", question_en]
    proc = subprocess.Popen(
        cmd,
        cwd=workdir,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace", env=env, **kwargs,
    )

    def _drain(out, f):
        try:
            for line in out:
                f.write(line)
                f.flush()
        except Exception:
            pass
        finally:
            try:
                f.close()
            except Exception:
                pass

    threading.Thread(target=_drain, args=(proc.stdout, logf), daemon=True).start()
    info = {
        "run_id": run_id, "question": question, "quality": quality,
        "pid": proc.pid, "status": "running", "started": time.time(),
        "log": log_path, "progress_path": progress_path,
        "user": user,
    }
    RUNS[run_id] = info
    _save_runs()
    _sync_record(run_id)   # 启动即写入用户历史（status=running）

    def _watch(pid, q, started, rid):
        try:
            proc.wait()
        except Exception:
            pass
        info = RUNS.get(rid, {})
        log_path = info.get("log")
        tail = ""
        if log_path and os.path.isfile(log_path):
            try:
                with open(log_path, encoding="utf-8", errors="replace") as f:
                    tail = "\n".join(f.read().splitlines()[-12:])
            except Exception:
                pass
        pp = info.get("progress_path")
        # 提前退出（15 秒内结束且没有进度文件）→ 判定失败，把子进程输出尾部带给前端
        if time.time() - started < 15 and not (pp and os.path.isfile(pp)):
            info["status"] = "error"
            info["error_msg"] = "子进程提前退出，未生成结果。日志尾部：\n" + (tail or "(无日志)")
            _sync_record(rid)
            _save_runs()
            return
        found = None
        try:
            found = _find_state_for_run(q, started - 5)
        except Exception:
            found = None
        if found:
            _, sj, st = found
            if st.get("error"):
                info["status"] = "error"
                info["error_msg"] = str(st.get("error"))[:800]
                _save_runs()
                return
            info["status"] = "done"
            info["state_path"] = sj
            info["best_score"] = st.get("best_score")
            info["best_data_score"] = st.get("best_data_score")
            info["hypothesis"] = (st.get("best_hypothesis") or st.get("hypothesis") or "")[:4000]
            info["plan_status"] = st.get("plan_status")
            info["evidence_status"] = st.get("evidence_status")
            info["final_answer"] = str(st.get("final_answer") or "")[:6000]
            info["rounds"] = len(st.get("score_history") or [])
            info["folder"] = os.path.dirname(sj)
            info["cost_cny"] = st.get("api_cost_cny")
            info["api_usage"] = st.get("api_usage")
            info["knowledge_tree"] = _tree_for_frontend(st)
            info["knowledge_gaps"] = st.get("knowledge_gaps") or []
        else:
            info["status"] = "done_no_state"
            if tail:
                info["error_msg"] = "运行结束但未找到结果文件。日志尾部：\n" + tail
        _sync_record(rid)
        _save_runs()

    threading.Thread(target=_watch, args=(proc.pid, question, info["started"], run_id), daemon=True).start()
    return run_id


def _resume_watch(rid, info):
    """服务重启后接管遗留 running 任务：进程结束 -> 查找 state -> 更新为 done。"""
    pid = info.get("pid")
    q = info.get("question")
    started = info.get("started") or time.time()

    def _loop():
        while _pid_alive(pid):
            time.sleep(10)
        time.sleep(3)
        found = _find_state_for_run(q, started - 5)
        cur = RUNS.get(rid, {})
        if found:
            _, sj, st = found
            cur["status"] = "done"
            cur["state_path"] = sj
            cur["best_score"] = st.get("best_score")
            cur["best_data_score"] = st.get("best_data_score")
            cur["hypothesis"] = (st.get("best_hypothesis") or st.get("hypothesis") or "")[:4000]
            cur["plan_status"] = st.get("plan_status")
            cur["evidence_status"] = st.get("evidence_status")
            cur["final_answer"] = str(st.get("final_answer") or "")[:6000]
            cur["rounds"] = len(st.get("score_history") or [])
            cur["folder"] = os.path.dirname(sj)
            cur["cost_cny"] = st.get("api_cost_cny")
            cur["api_usage"] = st.get("api_usage")
            cur["knowledge_tree"] = _tree_for_frontend(st)
            cur["knowledge_gaps"] = st.get("knowledge_gaps") or []
        else:
            cur["status"] = "done_no_state"
        _sync_record(rid)
        _save_runs()

    threading.Thread(target=_loop, daemon=True).start()


def run_status(run_id):
    info = RUNS.get(run_id)
    if not info:
        return None
    # 进程可能已退出但 watch 没更新
    if info.get("status") == "running" and not _pid_alive(info.get("pid")):
        info["status"] = "finishing"
    # 实时进度：子进程每阶段写 progress.json，轮询时读出来随响应返回
    pp = info.get("progress_path")
    if pp and os.path.isfile(pp):
        try:
            with open(pp, encoding="utf-8") as f:
                info["progress"] = json.load(f)
        except Exception:
            pass
    return info


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, code, body, mime, filename=None):
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Access-Control-Allow-Origin", "*")
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/mock":
            state = (parse_qs(u.query).get("state") or ["done"])[0]
            self._send(200, _mock_run(state))
            return
        # 静态资源：web/ 目录（支持多文件前端；/ 默认 index.html）
        if not u.path.startswith("/api/"):
            rel = u.path.lstrip("/") or "index.html"
            fp = os.path.normpath(os.path.join(WEB_DIR, rel))
            base = os.path.normpath(WEB_DIR)
            if os.path.commonpath([base, fp]) == base and os.path.isfile(fp):
                ext = os.path.splitext(fp)[1].lower()
                mime = _MIME.get(ext, "application/octet-stream")
                with open(fp, "rb") as f:
                    body = f.read()
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if u.path not in ("/", "/index.html"):
                self._send(404, {"error": "not found"})
                return
        # ---- 多用户历史（2026-08-28）----
        if u.path == "/api/history":
            user = (parse_qs(u.query).get("user") or [""])[0]
            ok_u, username, err_u = _login_user(user)
            if not ok_u:
                self._send(400, {"error": err_u})
                return
            try:
                sys.path.insert(0, SRC)
                import user_store
                self._send(200, {"username": username, "history": user_store.list_history(username)})
            except Exception as e:
                self._send(500, {"error": "读取历史失败：" + str(e)})
            return
        mhd = re.match(r"^/api/history/([^/]+)$", u.path)
        if mhd:
            user = (parse_qs(u.query).get("user") or [""])[0]
            ok_u, username, err_u = _login_user(user)
            if not ok_u:
                self._send(400, {"error": err_u})
                return
            try:
                sys.path.insert(0, SRC)
                import user_store
                detail = user_store.get_detail(username, mhd.group(1))
                if not detail:
                    self._send(404, {"error": "记录不存在"})
                    return
                self._send(200, detail)
            except Exception as e:
                self._send(500, {"error": "读取记录失败：" + str(e)})
            return
        mhe = re.match(r"^/api/history/([^/]+)/export$", u.path)
        if mhe:
            user = (parse_qs(u.query).get("user") or [""])[0]
            ok_u, username, err_u = _login_user(user)
            if not ok_u:
                self._send(400, {"error": err_u})
                return
            rid = mhe.group(1)
            try:
                sys.path.insert(0, SRC)
                import user_store
                rec = user_store.get_record(username, rid)
                folder = rec.get("folder") if rec else None
                if not folder or not os.path.isdir(folder):
                    self._send(404, {"error": "该记录没有结果文件夹（可能已被清理）"})
                    return
                fmt = (parse_qs(u.query).get("fmt") or ["html"])[0]
                sys.path.insert(0, SRC)
                import export_result as er
                d = er.collect(folder, with_plot=True)
                if fmt == "md":
                    text, ext, mime = er.render_md(d), "md", "text/markdown; charset=utf-8"
                else:
                    text, ext, mime = er.render_html(d), "html", "text/html; charset=utf-8"
                self._send_bytes(200, text.encode("utf-8"), mime, "结果报告_%s.%s" % (rid, ext))
            except Exception as e:
                self._send(500, {"error": "导出失败：" + str(e)})
            return

        m = re.match(r"^/api/run/([^/]+)$", u.path)
        mf = re.match(r"^/api/run/([^/]+)/feedback$", u.path)
        m_exp = re.match(r"^/api/run/([^/]+)/export$", u.path)
        if u.path == "/api/profile":
            user = (parse_qs(u.query).get("user") or ["guest"])[0]
            ok_u, username, err_u = _login_user(user)
            if not ok_u:
                self._send(400, {"error": err_u})
                return
            try:
                sys.path.insert(0, SRC)
                import user_profile
                self._send(200, user_profile.get_profile_for_api(username))
            except Exception as e:
                self._send(200, {"ready": False, "reason": "画像服务异常：%s" % e,
                                 "profile": None, "backend": None, "updated_at": None})
            return
        if u.path == "/api/runs":
            items = sorted(RUNS.items(), key=lambda kv: kv[1].get("started", 0), reverse=True)[:20]
            self._send(200, {"runs": [{"run_id": k, "question": v.get("question"), "status": v.get("status"),
                                       "best_score": v.get("best_score")} for k, v in items]})
        elif m:
            st = run_status(m.group(1))
            self._send(200, st if st else {"error": "run not found"})
        elif m_exp:
            rid = m_exp.group(1)
            folder = RUNS.get(rid, {}).get("folder")
            if not folder:
                self._send(404, {"error": "任务还未完成或没有结果目录，请等运行结束后再导出"})
                return
            fmt = (parse_qs(u.query).get("fmt") or ["html"])[0]
            try:
                sys.path.insert(0, SRC)
                import export_result as er
                d = er.collect(folder, with_plot=True)
                if fmt == "md":
                    text, ext, mime = er.render_md(d), "md", "text/markdown; charset=utf-8"
                else:
                    text, ext, mime = er.render_html(d), "html", "text/html; charset=utf-8"
                self._send_bytes(200, text.encode("utf-8"), mime, "结果报告_%s.%s" % (rid, ext))
            except Exception as e:
                self._send(500, {"error": "导出失败：" + str(e)})
        elif mf:
            rid = mf.group(1)
            fp = os.path.join(SRC, "..", "..", "..", "..")
            folder = RUNS.get(rid, {}).get("folder")
            if not folder:
                self._send(404, {"error": "no folder"})
                return
            try:
                sys.path.insert(0, SRC)
                import human_loop
                fb = human_loop.load_feedback(folder)
                self._send(200, {"feedback": fb})
            except Exception as e:
                self._send(500, {"error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        u = urlparse(self.path)
        m = re.match(r"^/api/run/([^/]+)/feedback$", u.path)
        mdel = re.match(r"^/api/history/([^/]+)/delete$", u.path)
        if mdel:
            # 软删除历史（2026-08-30）：用户视角删除生效，数据保留供审计/行为分析
            body = self._read_body()
            user = str(body.get("user") or "").strip() or (parse_qs(u.query).get("user") or [""])[0]
            ok_u, username, err_u = _login_user(user)
            if not ok_u:
                self._send(400, {"error": err_u})
                return
            try:
                sys.path.insert(0, SRC)
                import user_store
                ok = user_store.delete_record(username, mdel.group(1))
                self._send(200, {"ok": ok, "run_id": mdel.group(1), "deleted": True})
            except Exception as e:
                self._send(500, {"error": "删除失败：" + str(e)})
            return
        if u.path == "/api/login":
            body = self._read_body()
            ok_u, username, err_u = _login_user((body.get("username") or "").strip())
            if not ok_u:
                self._send(400, {"error": err_u})
                return
            try:
                sys.path.insert(0, SRC)
                import user_store
                self._send(200, {"ok": True, "username": username,
                                 "history": user_store.list_history(username)})
            except Exception as e:
                self._send(500, {"error": "登录失败：" + str(e)})
            return
        if u.path == "/api/parse_doc":
            body = self._read_body()
            name = (body.get("name") or "").strip()
            data_b64 = body.get("data") or ""
            if not name or not data_b64:
                self._send(400, {"error": "name / data required"})
                return
            try:
                raw = base64.b64decode(data_b64)
            except Exception:
                self._send(400, {"error": "文件数据不是合法的 base64"})
                return
            res = extract_doc_text(name, raw)
            if res.get("error"):
                self._send(400, {"error": res["error"]})
            else:
                self._send(200, {"name": name, "text": res.get("text", ""), "chars": res.get("chars", 0),
                                 "warning": res.get("warning", ""), "source": res.get("source", "")})
            return
        if u.path == "/api/run":
            body = self._read_body()
            q = (body.get("question") or "").strip()
            if not q:
                self._send(400, {"error": "question required"})
                return
            err = _deepseek_key_error()
            if err:
                self._send(400, {"error": err})
                return
            running = sum(1 for v in RUNS.values() if v.get("status") == "running")
            if running >= MAX_CONCURRENT:
                self._send(429, {"error": "同时运行的任务已达 %d 个上限，请等当前任务完成后再试" % MAX_CONCURRENT})
                return
            papers = body.get("papers")
            if not isinstance(papers, list):
                papers = []
            papers = [str(x).strip() for x in papers if str(x).strip()][:3]

            # 多用户：本次运行归属到当前用户名（默认 guest）
            username = (body.get("username") or "").strip() or "guest"
            question_en = str(body.get("question_en") or "").strip()
            ok_u, username, err_u = _login_user(username)
            if not ok_u:
                self._send(400, {"error": err_u})
                return

            # 输入安全护栏：先拦违规提问（防止把系统当危险品制作指南用）
            guard = _guard_check(q, papers)
            if not guard.get("allowed", True):
                self._send(200, {"blocked": True, "guard": guard})
                return

            # 追问精修闸门：白名单/清晰问题直接跑；模糊问题先返回 2-3 个追问
            skip_clarify = bool(body.get("skip_clarify"))
            clarify = body.get("clarify")
            if skip_clarify:
                clarify = []
            elif clarify is None:
                gate = _clarify_gate(q, papers)
                if gate.get("need_clarify"):
                    self._send(200, {"need_clarify": True, "questions": gate.get("questions", []),
                                     "reason": gate.get("reason", "")})
                    return
                clarify = []
            if not isinstance(clarify, list):
                clarify = []
            clarify = [{"question": str(x.get("question") or "").strip(),
                        "answer": str(x.get("answer") or "").strip()}
                       for x in clarify if isinstance(x, dict) and str(x.get("answer") or "").strip()]

            # 追问回答与原问题合并后再过一遍安全护栏（防夹带违规/注入）
            if clarify:
                merged = _clarify_merge(q, clarify)
                guard2 = _guard_check(merged, papers)
                if not guard2.get("allowed", True):
                    self._send(200, {"blocked": True, "guard": guard2})
                    return
                guard = guard2

            rid = start_run(q, body.get("quality", "超好"), papers=papers, clarify=clarify,
                            user=username, question_en=question_en)
            if rid in RUNS:
                RUNS[rid]["guard"] = {k: guard.get(k) for k in
                                       ("checked_by", "verdict", "categories", "risk", "reason")}
                RUNS[rid]["clarify"] = clarify
                RUNS[rid]["user"] = username
                _save_runs()
            self._send(200, {"run_id": rid, "status": "started",
                             "guard": {k: guard.get(k) for k in
                                       ("checked_by", "verdict", "categories", "risk", "reason")}})
        elif u.path == "/api/translate":
            body = self._read_body()
            text = (body.get("text") or "").strip()
            if not text:
                self._send(400, {"error": "text required"})
                return
            try:
                sys.path.insert(0, SRC)
                import llm_client
                translated = llm_client.chat(
                    "请把下面这段科学问题翻译成地道的英文科学提问。要求：保留专业术语；中文就译为英文，英文则轻微润色；直接输出翻译结果，不要任何解释、引号或额外内容。\n\n" + text,
                    system="你是科研翻译助手，只输出翻译后的英文文本。"
                ).strip()
                self._send(200, {"translated": translated, "source": text})
            except Exception as e:
                self._send(500, {"error": "翻译失败：" + str(e)})
        elif m:
            body = self._read_body()
            folder = RUNS.get(m.group(1), {}).get("folder")
            if not folder:
                self._send(404, {"error": "no folder yet"})
                return
            try:
                sys.path.insert(0, SRC)
                import human_loop
                fb = human_loop.empty_feedback()
                fb["verdict"] = body.get("verdict", "未评价")
                fb["questions"] = body.get("questions") or []
                fb["suggestions"] = body.get("suggestions") or []
                fp = human_loop.save_feedback(folder, fb)
                self._send(200, {"saved": fp})
            except Exception as e:
                self._send(500, {"error": str(e)})
            else:
                self._send(404, {"error": "not found"})

    def do_DELETE(self):
        """DELETE /api/run/{run_id}?user=xxx —— 软删除历史（2026-08-30）。
        用户视角删除生效（列表/详情/画像排除），数据保留供审计与行为分析。"""
        u = urlparse(self.path)
        m = re.match(r"^/api/run/([^/]+)$", u.path)
        if not m:
            self._send(404, {"error": "not found"})
            return
        user = (parse_qs(u.query).get("user") or [""])[0]
        ok_u, username, err_u = _login_user(user)
        if not ok_u:
            self._send(400, {"error": err_u})
            return
        try:
            sys.path.insert(0, SRC)
            import user_store
            ok = user_store.delete_record(username, m.group(1))
            self._send(200, {"ok": ok, "run_id": m.group(1), "deleted": True})
        except Exception as e:
            self._send(500, {"error": "删除失败：" + str(e)})


def main():
    host = "127.0.0.1"
    port = 8000
    if "--port" in sys.argv:
        i = sys.argv.index("--port")
        port = int(sys.argv[i + 1])
    if "--host" in sys.argv:
        i = sys.argv.index("--host")
        host = sys.argv[i + 1]
    _load_runs()
    # 服务重启后接管遗留的 running 任务（进程还活着则继续跟踪，跑完自动更新状态）
    for rid, info in list(RUNS.items()):
        if info.get("status") == "running":
            _resume_watch(rid, info)
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"AI Scientist API 已启动：http://{host}:{port}  （Ctrl+C 停止）")
    if host in ("0.0.0.0", "::"):
        try:
            import socket
            ips = socket.gethostbyname_ex(socket.gethostname())[2]
            lan = [x for x in ips if x.startswith(("192.168.", "10.", "172."))] or ips
            print("局域网访问：http://%s:%s  （同学在同一个 WiFi 下打开这个地址）" % (lan[0], port))
        except Exception:
            pass
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")


if __name__ == "__main__":
    main()
