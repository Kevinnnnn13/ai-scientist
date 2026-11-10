"""demo_hypothesis.py：端到端演示 —— 给一个研究问题，产出 12 字段科学假设报告

用法：
    python src/demo_hypothesis.py
    python src/demo_hypothesis.py "你的研究问题"
"""
import json
import os
import sys

from llm_client import json_chat
from schemas import HYPOTHESIS_SCHEMA, SYSTEM_HINT

PROMPT_TEMPLATE = """请针对下面的研究问题，生成一份完整的科学假设报告（JSON 格式）。

研究问题：{question}

字段要求（共 12 个，全部必填）：
{fields}

额外要求：
1. 只输出 JSON 对象本身；
2. 数组字段（技术手段、参考文献）至少 2 个元素；
3. 「结果」字段写预期结果即可，不要编造实验数据。"""


def fields_preview(schema):
    lines = []
    for name, spec in schema["properties"].items():
        t = spec.get("type", "?")
        desc = spec.get("description", "")
        lines.append(f'- "{name}"（{t}）：{desc}')
    return "\n".join(lines)


def main():
    default_q = "锂离子电池循环充放电时容量会逐渐衰减，如何用早期数据预测电池剩余寿命（RUL）？"
    question = sys.argv[1] if len(sys.argv) > 1 else default_q

    prompt = PROMPT_TEMPLATE.format(
        question=question,
        fields=fields_preview(HYPOTHESIS_SCHEMA),
    )
    result = json_chat(prompt, system=SYSTEM_HINT, schema=HYPOTHESIS_SCHEMA)

    print(json.dumps(result, ensure_ascii=False, indent=2))

    out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
    out_path = os.path.join(out_dir, "hypothesis.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"\n已保存到：{out_path}")


if __name__ == "__main__":
    main()