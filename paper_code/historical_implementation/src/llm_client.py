"""llm_client.py：统一 LLM 客户端 —— 一个接口，三后端（DeepSeek / Qwen / Ollama）

第 3 天新增：json_chat —— 强制结构化输出（JSON）+ 校验 + 自动重试
Qwen 后端 —— 阿里云百炼 DashScope（OpenAI 兼容），本地 Ollama Qwen 作离线兜底
"""
import json
import os
import re
import sys
import time
from datetime import datetime, time as dt_time, timedelta, timezone

from dotenv import load_dotenv
from openai import OpenAI

from logger import get_logger

# 打包（exe）态：.env 在 exe 同目录；开发态：默认当前工作目录
if getattr(sys, "frozen", False):
    load_dotenv(os.path.join(os.path.dirname(sys.executable), ".env"))
else:
    load_dotenv()
logger = get_logger("llm")

_LAST_JSON_PERF = {}   # L5：最近一次 json_chat 的性能记录（attempts/duration_s/tokens），JSONL 落盘用
_USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}   # 本次进程累计 token 用量（算钱用）

# DeepSeek 官方峰时（UTC）：周一至周五 01:00-04:00、06:00-10:00。
# 其他时段均为低价；中国法定节假日整日低价。为避免误判节假日，本保护采用保守规则：
# 除非在 DEEPSEEK_OFF_PEAK_EXTRA_DATES 里显式登记，否则工作日峰时一律阻止调用。
DEEPSEEK_PEAK_UTC_WINDOWS = (
    (dt_time(1, 0), dt_time(4, 0)),
    (dt_time(6, 0), dt_time(10, 0)),
)


class DeepSeekOffPeakError(RuntimeError):
    """DeepSeek 峰时调用被成本保护拦截。"""


def is_deepseek_off_peak(now_utc=None):
    """按 DeepSeek 官方规则判断当前是否处于低价时段。"""
    now_utc = now_utc or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    local_date = (now_utc + timedelta(hours=8)).date().isoformat()
    extra_off_peak_dates = {
        item.strip()
        for item in os.getenv("DEEPSEEK_OFF_PEAK_EXTRA_DATES", "").split(",")
        if item.strip()
    }
    if local_date in extra_off_peak_dates:
        return True

    if now_utc.weekday() >= 5:
        return True

    current = now_utc.time().replace(tzinfo=None)
    return not any(start <= current < end for start, end in DEEPSEEK_PEAK_UTC_WINDOWS)


def require_deepseek_off_peak(now_utc=None):
    """确保 DeepSeek 请求只在低价时段发出；默认启用，可用环境变量显式关闭。"""
    enabled = os.getenv("DEEPSEEK_OFF_PEAK_ONLY", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return
    if not is_deepseek_off_peak(now_utc):
        raise DeepSeekOffPeakError(
            "DeepSeek 当前属于峰时，已阻止调用以控制费用。"
            "峰时为北京时间周一至周五 09:00-12:00、14:00-18:00；"
            "其他时段及周末为低价时段。"
            "若因紧急情况必须例外，临时设置 DEEPSEEK_OFF_PEAK_ONLY=0。"
        )


def _acc_usage(usage):
    """把一次响应的 usage 累加到进程级计数器（每次 create 都算钱，包括失败重试）。"""
    global _USAGE
    if not usage:
        return
    try:
        pt = int(getattr(usage, "prompt_tokens", 0) or 0)
        ct = int(getattr(usage, "completion_tokens", 0) or 0)
        if pt or ct:
            _USAGE["prompt_tokens"] += pt
            _USAGE["completion_tokens"] += ct
            _USAGE["calls"] += 1
    except Exception:
        pass


def get_usage():
    """返回累计用量副本：{prompt_tokens, completion_tokens, calls}。"""
    return dict(_USAGE)


def reset_usage():
    global _USAGE
    _USAGE = {"prompt_tokens": 0, "completion_tokens": 0, "calls": 0}


def get_last_json_perf():
    """返回最近一次 json_chat 的性能记录副本；无记录返回空 dict。"""
    return dict(_LAST_JSON_PERF)


def _require_deepseek_key():
    """校验 DeepSeek Key：缺失 / 模板占位 / 含非 ASCII 一律给出可读错误，避免 httpx 头编码崩溃。"""
    key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "未检测到 DEEPSEEK_API_KEY：请编辑 exe 同目录（或项目根目录）的 .env 文件，"
            "填入 platform.deepseek.com 获取的 Key（形如 sk-xxxx）。"
        )
    if not key.startswith("sk-") or "填入" in key or "REPLACE" in key:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 看起来仍是模板占位符（当前值：" + key[:20] + "...），"
            "请在 .env 里填入真实 Key 后重启程序。"
        )
    try:
        key.encode("ascii")
    except UnicodeEncodeError:
        raise RuntimeError(
            "DEEPSEEK_API_KEY 含有非 ASCII 字符（可能是模板占位符），请填写真实 Key。"
        )
    return key


def _require_qwen_key():
    """校验 Qwen（阿里云百炼 DashScope）Key：缺失 / 模板占位 / 含非 ASCII 一律给出可读错误。"""
    key = os.getenv("QWEN_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "未检测到 QWEN_API_KEY：请编辑项目根目录的 .env 文件，"
            "填入阿里云百炼（DashScope）获取的 Key（形如 sk-xxxx）。"
        )
    if not key.startswith("sk-") or "填入" in key or "REPLACE" in key:
        raise RuntimeError(
            "QWEN_API_KEY 看起来仍是模板占位符（当前值：" + key[:20] + "...），"
            "请在 .env 里填入真实 Key 后重启程序。"
        )
    try:
        key.encode("ascii")
    except UnicodeEncodeError:
        raise RuntimeError(
            "QWEN_API_KEY 含有非 ASCII 字符（可能是模板占位符），请填写真实 Key。"
        )
    return key


def get_client():
    """按 LLM_BACKEND 选择后端，返回 (client, model_name)"""
    backend = os.getenv("LLM_BACKEND", "deepseek").strip().lower()

    if backend == "qwen":
        client = OpenAI(
            base_url=os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"),
            api_key=_require_qwen_key(),
        )
        model = os.getenv("QWEN_MODEL", "qwen-plus")
    elif backend == "ollama":
        client = OpenAI(
            base_url=os.getenv("OLLAMA_BASE_URL"),
            api_key="ollama",          # 本地不校验
        )
        model = os.getenv("OLLAMA_MODEL")
    else:
        require_deepseek_off_peak()
        client = OpenAI(
            base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            api_key=_require_deepseek_key(),
        )
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    return client, model


def active_model():
    """返回当前后端实际使用的模型名（供日志/元数据记录，保证可溯源）。"""
    backend = os.getenv("LLM_BACKEND", "deepseek").strip().lower()
    if backend == "qwen":
        return os.getenv("QWEN_MODEL", "qwen-plus")
    if backend == "ollama":
        return os.getenv("OLLAMA_MODEL", "")
    return os.getenv("DEEPSEEK_MODEL", "deepseek-chat")


def chat(prompt, system="你是一个乐于助人的AI助手。"):
    """普通对话接口：返回纯文本（带日志）。"""
    client, model = get_client()
    backend = os.getenv("LLM_BACKEND", "deepseek").strip().lower()
    if backend not in {"qwen", "ollama"}:
        require_deepseek_off_peak()
    t0 = time.time()
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    reply = resp.choices[0].message.content
    usage = getattr(resp, "usage", None)
    _acc_usage(usage)
    token_info = ""
    if usage and getattr(usage, "total_tokens", None):
        token_info = f" | tokens={usage.total_tokens}"
    logger.info(f"chat 成功 [{backend}/{model}] | 耗时 {time.time() - t0:.1f}s{token_info}")
    return reply


# ============ 结构化输出三件套：解析 / 校验 / 带重试的调用 ============

def extract_json(text):
    """把模型输出里的 JSON 抠出来（兼容 ```json 围栏和前后废话）"""
    if not text:
        return None
    text = text.strip()

    # 1. 如果有 markdown 代码块围栏，先剥掉
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if fence:
        text = fence.group(1).strip()

    # 2. 直接整体解析（模型很乖的时候一次就过）
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 3. 模型后面可能加了废话，用花括号配对找出真正的 JSON 主体
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _matches_type(value, want_type):
    """判断类型是否匹配，支持联合类型如 ["integer", "null"]"""
    if isinstance(want_type, list):
        if "null" in want_type and value is None:
            return True
        return any(_matches_type(value, t) for t in want_type if t != "null")
    if want_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if want_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if want_type == "string":
        return isinstance(value, str)
    if want_type == "array":
        return isinstance(value, list)
    if want_type == "object":
        return isinstance(value, dict)
    if want_type == "boolean":
        return isinstance(value, bool)
    return True


def _validate_dict(value, spec, prefix=""):
    """校验嵌套对象：按 spec 的 required/properties 递归检查"""
    errors = []
    props = spec.get("properties", {})
    for field in spec.get("required", []):
        if field not in value:
            errors.append(f"{prefix}缺少必填字段：{field}")
            continue
        v = value[field]
        s = props.get(field, {})
        wt = s.get("type")
        if wt is None:
            continue
        if not _matches_type(v, wt):
            if isinstance(wt, list):
                errors.append(f"{prefix}字段「{field}」类型不符：应为 {' / '.join(wt)}，实际是 {type(v).__name__}")
            else:
                errors.append(f"{prefix}字段「{field}」类型不符：应为 {wt}，实际是 {type(v).__name__}")
            continue
        if wt == "string" or (isinstance(wt, list) and "string" in wt):
            if isinstance(v, str) and not v.strip():
                errors.append(f"{prefix}字段「{field}」是空字符串")
        elif wt == "object" or (isinstance(wt, list) and "object" in wt):
            if isinstance(v, dict) and s.get("properties"):
                errors.extend(_validate_dict(v, s, f"{prefix}字段「{field}」："))
    return errors


def validate_against_schema(obj, schema):
    """按 Schema 验收输出，返回错误清单（空列表 = 通过）。支持嵌套 object 与 null 联合类型。"""
    errors = []
    if not isinstance(obj, dict):
        return [f"输出不是 JSON 对象，而是 {type(obj).__name__}"]

    props = schema.get("properties", {})
    for field in schema.get("required", []):
        if field not in obj:
            errors.append(f"缺少必填字段：{field}")
            continue

        value = obj[field]
        spec = props.get(field, {})
        want_type = spec.get("type")

        if want_type is None:
            continue
        if not _matches_type(value, want_type):
            if isinstance(want_type, list):
                errors.append(f"字段「{field}」类型不符：应为 {' / '.join(want_type)}，实际是 {type(value).__name__}")
            else:
                errors.append(f"字段「{field}」类型不符：应为 {want_type}，实际是 {type(value).__name__}")
            continue

        if want_type == "string" or (isinstance(want_type, list) and "string" in want_type):
            if isinstance(value, str) and not value.strip():
                errors.append(f"字段「{field}」是空字符串")
        elif want_type == "array" or (isinstance(want_type, list) and "array" in want_type):
            if isinstance(value, list):
                if len(value) == 0 and not spec.get("allowEmpty"):
                    errors.append(f"字段「{field}」是空数组")
                item_spec = spec.get("items", {})
                item_type = item_spec.get("type")
                for idx, item in enumerate(value):
                    if item_type == "string" and not isinstance(item, str):
                        errors.append(f"字段「{field}」第 {idx} 个元素应为字符串")
                    elif item_type == "object" and not isinstance(item, dict):
                        errors.append(f"字段「{field}」第 {idx} 个元素应为对象")
                    elif item_type == "object" and isinstance(item, dict) and item_spec.get("properties"):
                        errors.extend(_validate_dict(item, item_spec, f"字段「{field}」第 {idx} 项："))
        elif want_type == "object" or (isinstance(want_type, list) and "object" in want_type):
            if isinstance(value, dict) and spec.get("properties"):
                errors.extend(_validate_dict(value, spec, f"字段「{field}」："))

    if schema.get("additionalProperties") is False:
        allowed = set(props.keys())
        for field in obj:
            if field not in allowed:
                errors.append(f"出现 Schema 之外的字段：「{field}」")

    return errors


class JsonChatError(RuntimeError):
    """json_chat 连续失败时抛出，携带最后一次原始输出，供调用方走解析兜底链"""

    def __init__(self, message, last_content=None):
        super().__init__(message)
        self.last_content = last_content


def json_chat(prompt, system="", schema=None, max_retries=3):
    """强约束对话：返回 dict。失败自动重试，并把错误清单回喂给模型自纠错。

    - DeepSeek 后端：response_format=json_object（官方 JSON 模式）
    - Ollama 后端：不传 format（本地模型靠提示词约束 + extract_json 兜底，避免 SDK 参数差异）
    """
    client, model = get_client()
    backend = os.getenv("LLM_BACKEND", "deepseek").strip().lower()

    extra = {}
    if backend != "ollama":
        # DeepSeek 官方 JSON 模式：要求 prompt 里出现 "json" 字样（我们的 system 里有）
        extra["response_format"] = {"type": "json_object"}
        # 统一兜底（2026-08-29）：system 与 user prompt 都没有 "json" 字样时，
        # DeepSeek 会返回 400（"Prompt must contain the word 'json'"）。自动在 user prompt 末尾补一句，
        # 避免新增模块（如 frontier_scan）因提示词没写 "json" 而整轮失败。
        if "json" not in ((system or "") + "\n" + (prompt or "")).lower():
            prompt = (prompt or "") + "\n（请以 JSON 格式输出。）"

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]

    t0 = time.time()
    last_error = ""
    last_content = None
    for attempt in range(max_retries + 1):
        try:
            if backend not in {"qwen", "ollama"}:
                require_deepseek_off_peak()
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,          # 结构化输出要确定性，不要创意
                **extra,
            )
            content = resp.choices[0].message.content
            last_content = content
            _acc_usage(getattr(resp, "usage", None))
            obj = extract_json(content)
            errors = validate_against_schema(obj, schema) if obj is not None else ["解析 JSON 失败"]

            if not errors:
                usage = getattr(resp, "usage", None)
                token_info = ""
                if usage and getattr(usage, "total_tokens", None):
                    token_info = f" | tokens={usage.total_tokens}"
                logger.info(f"json_chat 成功 [{backend}/{model}] 第 {attempt + 1} 次调用"
                            f" | 耗时 {time.time() - t0:.1f}s{token_info}")
                _LAST_JSON_PERF.clear()
                _LAST_JSON_PERF.update({
                    "attempts": attempt + 1,
                    "duration_s": round(time.time() - t0, 2),
                    "tokens": int(usage.total_tokens) if usage and getattr(usage, "total_tokens", None) else None,
                })
                return obj

            last_error = "；".join(errors)
            logger.warning(f"json_chat 第 {attempt + 1} 次失败 [{backend}/{model}]：{last_error}")
            messages.append({"role": "assistant", "content": content})
            example_hint = ""
            if schema and isinstance(schema, dict) and isinstance(schema.get("properties"), dict):
                ex_lines = []
                for fname, spec in schema["properties"].items():
                    if isinstance(spec, dict) and spec.get("examples"):
                        wt = spec.get("type")
                        if isinstance(wt, list):
                            wt = wt[0] if wt else None
                        if wt == "array":
                            ex_lines.append('"%s": %s' % (fname, json.dumps(spec["examples"], ensure_ascii=False)))
                        else:
                            ex_lines.append('"%s": %s' % (fname, json.dumps(spec["examples"][0], ensure_ascii=False)))
                if ex_lines:
                    example_hint = ("\n易错字段的合法形态示例（必须严格按此形态输出）：\n{\n  "
                                    + ",\n  ".join(ex_lines) + "\n}\n")
            messages.append({"role": "user",
                             "content": f"你上次的输出不符合要求：{last_error}\n"
                                        f"{example_hint}请严格按规则重新输出一个完整的 JSON 对象。"})

        except Exception as e:
            last_error = f"API 异常：{e}"
            logger.error(f"json_chat 第 {attempt + 1} 次异常 [{backend}/{model}]：{e}")
            time.sleep(1)   # 网络抖动的简单退避

    raise JsonChatError(f"json_chat 连续失败 {max_retries + 1} 次，最后错误：{last_error}", last_content)


if __name__ == "__main__":
    print("请选择后端：")
    print("  1 = DeepSeek（云端）")
    print("  2 = Qwen（阿里云百炼 DashScope）")
    print("  3 = Ollama（本地）")
    choice = input("请输入 1 / 2 / 3：").strip()

    if choice == "1":
        os.environ["LLM_BACKEND"] = "deepseek"
    elif choice == "2":
        os.environ["LLM_BACKEND"] = "qwen"
    elif choice == "3":
        os.environ["LLM_BACKEND"] = "ollama"
    else:
        print("输入无效，默认用 DeepSeek")
        os.environ["LLM_BACKEND"] = "deepseek"

    print("=== 当前后端:", os.getenv("LLM_BACKEND"), "===")
    question = input("请输入你的问题：")
    print(chat(question))
