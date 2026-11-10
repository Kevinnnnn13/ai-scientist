"""第1个程序：调用 DeepSeek 官方 API（OpenAI 兼容接口）"""
import os
from dotenv import load_dotenv

import llm_client

load_dotenv()

client, model = llm_client.get_client()

resp = client.chat.completions.create(
    model=model,
    messages=[
        {"role": "system", "content": "你是一个乐于助人的AI助手。"},
        {"role": "user", "content": "你好，请用一句话介绍你自己。"},
    ],
    temperature=0.7,
    top_p=0.8,
)

print("回复：", resp.choices[0].message.content)
