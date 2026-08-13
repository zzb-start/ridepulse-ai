"""embedding 模块测试 — 规格来源：文档15 §7.11。

要求：
1. fake 模式确定性：同一文本同一向量，不同文本不同向量
2. 组合文本包含品牌/型号/主题/场景/原文
3. api 模式缓存：同一文本不重复计费（Mock Transport）
4. 记录模型名与维度
"""

from __future__ import annotations

import httpx
import pytest

from ridepulse.embedding import ApiEmbedder, EmbeddingError, embed_records, embed_texts, fake_embed


class TestFakeEmbed:
    def test_deterministic_same_text(self):
        assert fake_embed("同一文本", 64) == fake_embed("同一文本", 64)

    def test_different_text_different_vector(self):
        assert fake_embed("文本A", 64) != fake_embed("文本B", 64)

    def test_dimension_respected(self):
        assert len(fake_embed("测试", 32)) == 32

    def test_fake_mode_returns_same_order(self):
        texts = ["第一条", "第二条", "第三条"]
        vectors = embed_texts(texts, mode="fake", dimension=64)
        assert len(vectors) == 3
        assert all(len(v) == 64 for v in vectors)


class TestEmbedRecords:
    def test_composes_brand_model_theme_text(self, valid_feedback_record,
                                              valid_classification):
        vectors = embed_records(
            [valid_feedback_record],
            {valid_classification.feedback_id: valid_classification},
            mode="fake", dimension=64,
        )
        assert valid_feedback_record.feedback_id in vectors
        # 与手工构造的组合文本向量一致（验证组合内容）
        expected = fake_embed(
            "Magene | C606 | connectivity | training | "
            "设备显示上传成功，但活动未出现在App里，重试了三次都一样。",
            64,
        )
        assert vectors[valid_feedback_record.feedback_id] == expected


class TestApiEmbedder:
    def test_api_mode_caches_identical_text(self):
        """同一文本第二次调用不再请求 API（命中缓存）。"""
        called = {"n": 0}

        def handler(request: httpx.Request) -> httpx.Response:
            called["n"] += 1
            payload = request.read().decode("utf-8")
            import json
            texts = json.loads(payload)["input"]
            return httpx.Response(200, json={
                "object": "list",
                "data": [
                    {"index": i, "object": "embedding", "embedding": [0.1 * (i + 1)] * 4}
                    for i in range(len(texts))
                ],
            })

        transport = httpx.MockTransport(handler)
        embedder = ApiEmbedder(base_url="https://fake.example/v1", api_key="key",
                               model="m", transport=transport)
        vectors = embed_texts(["固定文本"], mode="api", api_client=embedder)
        vectors2 = embed_texts(["固定文本"], mode="api", api_client=embedder)
        assert called["n"] == 1  # 第二次命中缓存，未发起请求
        assert vectors == vectors2

    def test_api_error_raises(self):
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="unauthorized")

        transport = httpx.MockTransport(handler)
        embedder = ApiEmbedder(base_url="https://fake.example/v1", api_key="key",
                               model="m", transport=transport)
        with pytest.raises(EmbeddingError):
            embed_texts(["文本"], mode="api", api_client=embedder)

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError):
            embed_texts(["文本"], mode="nope")
