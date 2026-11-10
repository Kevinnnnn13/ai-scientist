# -*- coding: utf-8 -*-
"""语义检索层：embedding 向量召回（独立模块，可挂到检索/知识整合前）。

设计：
- 首选：DeepSeek embedding API（OpenAI 兼容接口，复用 llm_client.get_client）
- 兜底：TF-IDF（sklearn），零依赖可用
- 向量库用 numpy 实现（不依赖 faiss）

用法：
  from semantic_search import SemanticIndex
  idx = SemanticIndex()
  idx.add(["perovskite solar cell 稳定性", "锂离子电池寿命预测", ...])
  hits = idx.search("钙钛矿太阳能电池的稳定性", top_k=3)
"""
import os
import re
import sys
import numpy as np

SRC = os.path.dirname(os.path.abspath(__file__))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "deepseek-embedding")
# 默认走 TF-IDF（本机 DeepSeek 网关无 embedding 接口，省去每次 404）；接入真 embedding 服务时设 EMBEDDING_ENABLED=1
EMBEDDING_ENABLED = os.getenv("EMBEDDING_ENABLED", "0") == "1"


def _cosine(a, b):
    na = np.linalg.norm(a)
    nb = np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


class SemanticIndex:
    def __init__(self):
        self._texts = []
        self._vecs = None       # numpy matrix (n, d)
        self._mode = "none"     # embedding | tfidf
        self._tfidf = None
        self._tfidf_vecs = None

    # ---- embedding ----
    def _embed_api(self, texts):
        try:
            from llm_client import get_client
            client = get_client()
            resp = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
            vecs = [d.embedding for d in resp.data]
            return np.array(vecs, dtype="float32")
        except Exception as e:
            self._last_error = str(e)[:150]
            return None

    # ---- tfidf 兜底 ----
    def _tfidf_vec(self, texts):
        from sklearn.feature_extraction.text import TfidfVectorizer
        if self._tfidf is None:
            self._tfidf = TfidfVectorizer(lowercase=True, analyzer="char_wb", ngram_range=(2, 3))
            self._tfidf_vecs = self._tfidf.fit_transform(texts)
        else:
            self._tfidf_vecs = self._tfidf.transform(texts)
        return self._tfidf_vecs

    def add(self, texts):
        texts = [str(t) for t in texts]
        self._texts.extend(texts)
        if EMBEDDING_ENABLED:
            v = self._embed_api(texts)
            if v is not None:
                self._vecs = v if self._vecs is None else np.vstack([self._vecs, v])
                self._mode = "embedding"
                return
        # tfidf 兜底（增量重建，简单起见全量重算）
        self._tfidf = None
        self._tfidf_vec(texts)
        self._mode = "tfidf"

    def search(self, query, top_k=3):
        if not self._texts:
            return []
        if self._mode == "embedding" and self._vecs is not None:
            qv = self._embed_api([query])
            if qv is None:
                return self._search_tfidf(query, top_k)
            sims = [_cosine(qv[0], self._vecs[i]) for i in range(len(self._texts))]
        else:
            return self._search_tfidf(query, top_k)
        order = sorted(range(len(sims)), key=lambda i: -sims[i])[:top_k]
        return [{"text": self._texts[i], "score": round(sims[i], 4), "idx": i} for i in order]

    def _search_tfidf(self, query, top_k):
        if self._tfidf_vecs is None:
            return []
        qv = self._tfidf.transform([query]).toarray()[0]
        sims = []
        for i in range(len(self._texts)):
            row = np.asarray(self._tfidf_vecs[i].toarray()[0], dtype="float32")
            sims.append(_cosine(qv.astype("float32"), row))
        order = sorted(range(len(sims)), key=lambda i: -sims[i])[:top_k]
        return [{"text": self._texts[i], "score": round(sims[i], 4), "idx": i} for i in order]

    @property
    def mode(self):
        return self._mode


if __name__ == "__main__":
    idx = SemanticIndex()
    idx.add(["钙钛矿太阳能电池稳定性提升机制",
             "perovskite solar cell stability",
             "锂离子电池循环寿命预测",
             "machine learning for battery degradation"])
    for q in ["钙钛矿太阳能电池的稳定性", "电池寿命预测"]:
        print("Q:", q, "-> mode:", idx.mode)
        for h in idx.search(q, top_k=2):
            print("   ", h["score"], h["text"][:50])
# ===== 语义兜底层（2026-08-10 接入知识整合/检索过滤）=====
SEMANTIC_KEEP_MIN = float(os.getenv("SEMANTIC_KEEP_MIN", "0.16"))   # 中语义阈值（需词干锚点）
SEMANTIC_STRONG = float(os.getenv("SEMANTIC_STRONG", "0.25"))       # 强语义阈值（直接放行）


def _stem_en(w):
    """轻量英文词干（仅复数/常见后缀），用于词干锚点匹配。"""
    w = str(w).lower()
    if len(w) > 6 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 5 and w.endswith("es"):
        return w[:-2]
    if len(w) > 5 and w.endswith("s"):
        return w[:-1]
    return w


def term_anchor(node_texts, title):
    """词干锚点：node_texts 里任一 >=5 字符 term（词干化后）出现在标题中。"""
    tl = str(title or "").lower()
    if not tl:
        return False
    for t in node_texts:
        for term in re.split(r"[^a-z0-9]+", str(t).lower()):
            if len(term) >= 5 and _stem_en(term) in tl:
                return True
    return False


def title_semantic_scores(titles, query_text):
    """对一批标题建语义索引（embedding 优先，TF-IDF 兜底），返回 {标题: 相似度}。
    失败返回 {}（调用方按无语义层处理，行为不变）。"""
    titles = [str(t).strip() for t in titles if str(t).strip()]
    q = str(query_text or "").strip()
    if not titles or not q:
        return {}
    try:
        idx = SemanticIndex()
        idx.add(titles)
        hits = idx.search(q, top_k=len(titles))
    except Exception:
        return {}
    return {h["text"]: float(h["score"]) for h in hits}
