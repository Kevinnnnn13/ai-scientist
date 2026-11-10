# -*- coding: utf-8 -*-
"""AI Scientist 打包入口（PyInstaller 单 exe）。

两种角色：
- 无参数双击/运行：启动 API 服务 + 自动打开浏览器（给同学用的模式）
- --worker <问题> --quality <档>：作为假设生成子进程运行（api_server 内部自动调用）
"""
import os
import sys
import threading
import time

BASE = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else os.path.dirname(os.path.abspath(__file__))


def _env_key_ok():
    """检查 exe/项目目录 .env 里的 DeepSeek Key 是否真实可用（非模板占位）。"""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(BASE, ".env"))
        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not key or not key.startswith("sk-") or "填入" in key or "REPLACE" in key:
            return False
        key.encode("ascii")
        return True
    except Exception:
        return False


def _ensure_env_template():
    env_path = os.path.join(BASE, ".env")
    key_ok = _env_key_ok()
    if not key_ok and not os.path.exists(env_path):
        try:
            with open(env_path, "w", encoding="utf-8") as f:
                f.write("# AI Scientist 配置：填入你的 DeepSeek Key 后重启程序\n")
                f.write("DEEPSEEK_API_KEY=\n")
                f.write("DEEPSEEK_MODEL=deepseek-chat\n")
                f.write("DEEPSEEK_BASE_URL=https://api.deepseek.com/v1\n")
                f.write("LLM_BACKEND=deepseek\n")
        except Exception:
            pass
    return key_ok

def _open_browser(url):
    try:
        import webbrowser
        webbrowser.open(url)
    except Exception:
        pass


def main():
    if "--worker" in sys.argv:
        sys.argv.remove("--worker")
        if not _env_key_ok():
            print("=" * 56)
            print("[错误] 未检测到有效的 DEEPSEEK_API_KEY。")
            print("请编辑 exe 同目录下的 .env 文件，填入真实 Key（platform.deepseek.com 获取）")
            print("=" * 56)
            sys.exit(2)
        import langgraph_agent
        langgraph_agent.main()
        return

    key_ok = _ensure_env_template()
    if not key_ok:
        print("=" * 56)
        print("[提示] 未检测到 DeepSeek API Key。")
        print("请编辑 exe 同目录下的 .env 文件，填入 DEEPSEEK_API_KEY")
        print("（没有 Key 可到 platform.deepseek.com 注册，几元就够跑演示）")
        print("=" * 56)
        time.sleep(5)

    import api_server
    threading.Timer(3.0, lambda: _open_browser("http://127.0.0.1:8000/")).start()
    api_server.main()


if __name__ == "__main__":
    main()
