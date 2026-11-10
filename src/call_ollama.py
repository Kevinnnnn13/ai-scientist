"""第2个程序：调用本地 Ollama 上的 Qwen 小模型（免费、离线）"""
import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

client = OpenAI(
    base_url=os.getenv("OLLAMA_BASE_URL"),
    api_key="ollama",   # 本地不校验
)

resp = client.chat.completions.create(
    model=os.getenv("OLLAMA_MODEL"),
    messages=[{"role": "user", "content": "你好，请用一句话介绍你自己。"}],
)

print("回复：", resp.choices[0].message.content)