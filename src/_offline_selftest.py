"""离线自测：不调用任何 API，验证 解析/校验/重试 三个核心函数"""
import os, json
os.environ["LLM_BACKEND"] = "deepseek"

import llm_client as L

# ---- 1. extract_json ----
cases = [
    ('{"a":1}', {"a": 1}),                                  # 纯净 JSON
    ('```json\n{"a":1}\n```', {"a": 1}),                    # 带围栏
    ('好的，结果如下：{"a":1} 以上就是全部', {"a": 1}),      # 前后有废话
    ('不是 JSON', None),                                    # 完全不是
    ('', None),
]
for text, want in cases:
    got = L.extract_json(text)
    assert got == want, f"extract_json 失败: {text!r} -> {got}"
print("✓ extract_json 5 个用例全部通过")

# ---- 2. validate_against_schema ----
schema = {
    "type": "object",
    "properties": {
        "标题": {"type": "string"},
        "技术手段": {"type": "array", "items": {"type": "string"}},
        "结论": {"type": "string"},
    },
    "required": ["标题", "技术手段", "结论"],
    "additionalProperties": False,
}
good = {"标题": "x", "技术手段": ["a", "b"], "结论": "y"}
assert L.validate_against_schema(good, schema) == []
print("✓ 合法对象：错误清单为空")

bad = {"标题": "", "技术手段": ["a"], "乱入": 1}
errs = L.validate_against_schema(bad, schema)
print("  非法对象错误清单：", errs)
assert any("缺少必填字段：结论" in e for e in errs)
assert any("是空字符串" in e for e in errs)
assert any("Schema 之外" in e for e in errs)
print("✓ validate 能挑出：缺字段 / 空字符串 / 多余字段")

# ---- 3. json_chat 的重试循环（用假客户端模拟）----
class FakeResp:
    class Msg:
        def __init__(self, c): self.content = c
    def __init__(self, c):
        self.choices = [type("C", (), {"message": FakeResp.Msg(c)})()]
        self.usage = None

class FakeCompletions:
    def __init__(self, outputs): self.outputs = outputs; self.i = 0
    def create(self, **kw): c = self.outputs[min(self.i, len(self.outputs) - 1)]; self.i += 1; return FakeResp(c)

class FakeClient:
    def __init__(self, outputs): self.chat = type("Ch", (), {"completions": FakeCompletions(outputs)})()

# 情况 A：第一次输出残缺，第二次输出合法 → 应自动重试并成功
L.get_client = lambda: (FakeClient([
    '{"标题":"第一次"}' ,                                  # 缺字段，校验失败
    '{"标题":"ok","技术手段":["a","b"],"结论":"ok"}',      # 合法
]), "fake-model")
r = L.json_chat("测试", system="", schema=schema, max_retries=3)
assert r["标题"] == "ok"
print("✓ json_chat 自动重试后成功返回", r["标题"])

# 情况 B：一直输出垃圾 → 应抛 RuntimeError
L.get_client = lambda: (FakeClient(['不是 JSON', '还是不是']), "fake-model")
try:
    L.json_chat("测试", system="", schema=schema, max_retries=1)
    raise SystemExit("应该抛异常但没有")
except RuntimeError as e:
    print("✓ 连续失败正确抛出 RuntimeError")

print("\n全部离线自测通过 ✅")