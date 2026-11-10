"""use_llm.py：演示其他程序怎么调用封装好的客户端"""
from llm_client import chat

answer = chat("请用一句话解释什么是机器学习。")
print("AI 说：", answer)