"""LLM 客户端 — OpenAI 兼容接口。

实现要求（文档15 §7.7）：
1. Base URL / 模型名由环境变量指定
2. 温度默认 0，超时，最多重试 3 次（仅超时/限流/5xx）
3. 结构化 JSON 输出
4. JSON 解析失败只允许一次修复调用
5. 第二次仍失败进入人工队列，不生成猜测结果
6. 测试使用 Fake 客户端，不消耗真实 API
7. 记录模型名/耗时/token，不记录 Secret
"""

from __future__ import annotations

from typing import Any


class LLMClientError(Exception):
    """LLM 调用失败。"""


class BaseLLMClient:
    """LLM 客户端基类。"""

    def __init__(self, *, base_url: str, api_key: str, model: str,
                 timeout_seconds: int = 60, max_retries: int = 3) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        """调用模型并返回结构化 JSON。"""
        raise NotImplementedError("8月4日实现")


class FakeLLMClient(BaseLLMClient):
    """测试用假客户端 — 不消耗 API。"""

    def __init__(self, responder=None, **kwargs: Any) -> None:
        super().__init__(base_url="fake", api_key="fake", model="fake-model", **kwargs)
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> dict[str, Any]:
        self.calls.append((system, user))
        if self.responder is None:
            raise LLMClientError("FakeLLMClient 未配置 responder")
        return self.responder(system, user)
