"""logger.py：统一日志 —— 每次 LLM 调用都留痕，排障不用靠猜"""
import logging
import os

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
os.makedirs(LOG_DIR, exist_ok=True)


def get_logger(name="llm"):
    logger = logging.getLogger(name)
    if logger.handlers:          # 重复调用时避免叠加多个 handler
        return logger

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s")

    file_handler = logging.FileHandler(os.path.join(LOG_DIR, "llm.log"), encoding="utf-8")
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    logger.addHandler(console_handler)

    return logger