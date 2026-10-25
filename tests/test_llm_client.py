"""BaseLLMClient 测试 — 使用 httpx.MockTransport 模拟 HTTP 层，不消耗真实 API。

- 温度默认 0；超时；最多重试 max_retries 次，只对超时/429/5xx 重试
- 结构化 JSON 输出；解析失败只允许一次修复调用
- 第二次仍失败必须抛错（上层进入人工队列），不得生成猜测结果
- 记录模型名/耗时/token/状态，不记录 Secret
"""

from __future__ import annotations

import json
from typing import Callable

import httpx
import pytest

from ridepulse.llm_client import (
    BaseLLMClient,
    LLMClientError,
    capabilities_for,
    resolve_reasoning_effort,
)

BASE_URL = "https://api.example.test/v1"
API_KEY = "secret-test-key"
MODEL = "test-model"


def completion_response(content: str, *, tokens: dict | None = None) -> httpx.Response:
    """构造一次 OpenAI 兼容 chat/completions 成功响应。"""
    usage = tokens or {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}
    return httpx.Response(
        200,
        json={
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "model": MODEL,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": usage,
        },
    )


def make_client(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_retries: int = 3,
) -> tuple[BaseLLMClient, list[httpx.Request]]:
    """构造注入 MockTransport 的客户端，并记录所有请求。"""
    calls: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return handler(request)

    client = BaseLLMClient(
        base_url=BASE_URL,
        api_key=API_KEY,
        model=MODEL,
        transport=httpx.MockTransport(wrapped),
        backoff_base=0.0,
        max_retries=max_retries,
    )
    return client, calls


def sequential(*events) -> Callable[[httpx.Request], httpx.Response]:
    """按顺序返回预置响应；预置耗尽后断言失败（不应有多余请求）。"""
    queue = list(events)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            raise AssertionError("发生了超出预期的 HTTP 请求")
        event = queue.pop(0)
        if isinstance(event, Exception):
            raise event
        return event

    return handler


VALID_JSON = '{"feedback_id": "F0001", "theme_primary": "connectivity"}'


class TestSuccessPath:
    def test_returns_parsed_json(self):
        client, _ = make_client(sequential(completion_response(VALID_JSON)))
        result = client.complete_json("system", "user")
        assert result == {"feedback_id": "F0001", "theme_primary": "connectivity"}

    def test_sends_expected_request_shape(self):
        client, calls = make_client(sequential(completion_response(VALID_JSON)))
        client.complete_json("系统提示", "用户输入")
        request = calls[0]
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["Authorization"] == f"Bearer {API_KEY}"
        body = json.loads(request.content)
        assert body["model"] == MODEL
        assert body["temperature"] == 0
        assert body["response_format"] == {"type": "json_object"}
        assert body["messages"] == [
            {"role": "system", "content": "系统提示"},
            {"role": "user", "content": "用户输入"},
        ]

    def test_temperature_can_be_overridden(self):
        client, calls = make_client(sequential(completion_response(VALID_JSON)))
        client.complete_json("s", "u", temperature=0.7)
        assert json.loads(calls[0].content)["temperature"] == 0.7


class TestGpt6Payload:
    """GPT-6 系列不接受采样参数，推理深度改由 reasoning_effort 控制。"""

    def test_gpt6_omits_temperature_and_sends_reasoning_effort(self):
        client, calls = make_client(sequential(completion_response(VALID_JSON)))
        client.model = "gpt-6-astra"
        client.capabilities = capabilities_for(client.model)
        client.reasoning_effort = resolve_reasoning_effort(client.model, "medium")
        client.complete_json("s", "u")
        body = json.loads(calls[0].content)
        assert "temperature" not in body
        assert body["reasoning_effort"] == "medium"
        assert body["response_format"] == {"type": "json_object"}

    def test_gpt6_rejects_none_effort_and_falls_back_to_low(self):
        # GPT-6 取消了 none / minimal：配置成 none 不能静默发出去
        assert resolve_reasoning_effort("gpt-6-sol", "none") == "low"
        assert resolve_reasoning_effort("gpt-6-sol", "minimal") == "low"

    def test_gpt6_accepts_all_five_efforts(self):
        for effort in ("low", "medium", "high", "xhigh", "max"):
            assert resolve_reasoning_effort("gpt-6-luna", effort) == effort

    def test_unknown_effort_falls_back_to_low(self):
        assert resolve_reasoning_effort("gpt-6-luna", "turbo") == "low"

    def test_standard_model_keeps_temperature_and_no_effort(self):
        caps = capabilities_for("some-compatible-model")
        assert caps.supports_temperature is True
        assert resolve_reasoning_effort("some-compatible-model", "low") is None

    def test_rejected_param_is_dropped_and_retried(self):
        # 服务端明确报某个参数不支持：剔除该参数重试一次，而不是整条失败
        reject = httpx.Response(
            400,
            json={
                "error": {
                    "message": "Unsupported parameter: 'response_format'",
                    "type": "invalid_request_error",
                    "param": "response_format",
                    "code": "unsupported_parameter",
                }
            },
        )
        client, calls = make_client(
            sequential(reject, completion_response(VALID_JSON))
        )
        assert client.complete_json("s", "u")["feedback_id"] == "F0001"
        assert len(calls) == 2
        assert "response_format" not in json.loads(calls[1].content)

    def test_param_rejection_without_param_field_still_fails(self):
        # 没有 param 字段的 400 不做协商，避免把真实错误当成参数问题吞掉
        client, calls = make_client(sequential(httpx.Response(400, json={"error": "bad"})))
        with pytest.raises(LLMClientError, match="400"):
            client.complete_json("s", "u")
        assert len(calls) == 1


class TestRetry:
    def test_retries_on_5xx_then_succeeds(self):
        client, calls = make_client(
            sequential(httpx.Response(500), httpx.Response(503), completion_response(VALID_JSON))
        )
        result = client.complete_json("s", "u")
        assert result["feedback_id"] == "F0001"
        assert len(calls) == 3

    def test_retries_on_429_then_succeeds(self):
        client, calls = make_client(sequential(httpx.Response(429), completion_response(VALID_JSON)))
        assert client.complete_json("s", "u")["feedback_id"] == "F0001"
        assert len(calls) == 2

    def test_retries_on_timeout_then_succeeds(self):
        client, calls = make_client(
            sequential(httpx.ConnectTimeout("timeout", request=None), completion_response(VALID_JSON))
        )
        assert client.complete_json("s", "u")["feedback_id"] == "F0001"
        assert len(calls) == 2

    def test_gives_up_after_max_retries_on_5xx(self):
        client, _ = make_client(
            sequential(httpx.Response(500), httpx.Response(500), httpx.Response(500)),
            max_retries=2,
        )
        with pytest.raises(LLMClientError, match="500"):
            client.complete_json("s", "u")

    def test_does_not_retry_other_4xx(self):
        client, calls = make_client(sequential(httpx.Response(400, json={"error": "bad request"})))
        with pytest.raises(LLMClientError, match="400"):
            client.complete_json("s", "u")
        assert len(calls) == 1


class TestJsonParsing:
    def test_strips_markdown_fences_before_parsing(self):
        fenced = "```json\n" + VALID_JSON + "\n```"
        client, _ = make_client(sequential(completion_response(fenced)))
        assert client.complete_json("s", "u")["feedback_id"] == "F0001"

    def test_strips_think_block_prefix_before_parsing(self):
        # 推理模型偶尔会在正文前输出 <think>…</think>，解析前必须剥离
        with_think = "<think>用户要求输出JSON，先分析字段含义…</think>\n\n" + VALID_JSON
        client, _ = make_client(sequential(completion_response(with_think)))
        assert client.complete_json("s", "u")["feedback_id"] == "F0001"

    def test_extracts_json_from_surrounding_text(self):
        noisy = "好的，以下是分类结果：\n" + VALID_JSON + "\n希望以上信息对你有帮助"
        client, _ = make_client(sequential(completion_response(noisy)))
        assert client.complete_json("s", "u")["feedback_id"] == "F0001"

    def test_parse_failure_triggers_one_repair_call(self):
        client, calls = make_client(
            sequential(
                completion_response("抱歉，这不是JSON"),
                completion_response(VALID_JSON),
            )
        )
        assert client.complete_json("s", "u")["feedback_id"] == "F0001"
        assert len(calls) == 2
        # 修复调用的 user 消息必须包含原失败内容
        repair_body = json.loads(calls[1].content)
        assert "抱歉，这不是JSON" in repair_body["messages"][1]["content"]

    def test_parse_failure_twice_raises_no_guessed_result(self):
        client, calls = make_client(
            sequential(completion_response("坏1"), completion_response("坏2"))
        )
        with pytest.raises(LLMClientError, match="JSON"):
            client.complete_json("s", "u")
        assert len(calls) == 2


class TestUsageLog:
    def test_success_logs_model_status_tokens_duration(self):
        client, _ = make_client(
            sequential(
                completion_response(
                    VALID_JSON,
                    tokens={"prompt_tokens": 100, "completion_tokens": 40, "total_tokens": 140},
                )
            )
        )
        client.complete_json("s", "u")
        assert len(client.usage_log) == 1
        entry = client.usage_log[0]
        assert entry["model"] == MODEL
        assert entry["status"] == "success"
        assert entry["total_tokens"] == 140
        assert entry["prompt_tokens"] == 100
        assert entry["completion_tokens"] == 40
        assert entry["duration_ms"] >= 0
        assert entry["attempts"] >= 1

    def test_logs_reasoning_tokens(self):
        # 推理模型的思考 token 单独计入 usage，便于按档位核算成本
        client, _ = make_client(
            sequential(
                completion_response(
                    VALID_JSON,
                    tokens={
                        "prompt_tokens": 100, "completion_tokens": 60, "total_tokens": 160,
                        "completion_tokens_details": {"reasoning_tokens": 40},
                    },
                )
            )
        )
        client.complete_json("s", "u")
        assert client.usage_log[0]["reasoning_tokens"] == 40

    def test_failure_logs_failed_status_and_no_secret(self):
        client, _ = make_client(
            sequential(httpx.Response(500), httpx.Response(500), httpx.Response(500)),
            max_retries=2,
        )
        with pytest.raises(LLMClientError):
            client.complete_json("s", "u")
        entry = client.usage_log[-1]
        assert entry["status"] == "failed"
        assert entry["model"] == MODEL

    def test_log_never_contains_api_key(self):
        client, _ = make_client(sequential(completion_response(VALID_JSON)))
        client.complete_json("s", "u")
        assert API_KEY not in str(client.usage_log)

    def test_repeated_calls_append_log_entries(self):
        client, _ = make_client(
            sequential(completion_response(VALID_JSON), completion_response(VALID_JSON))
        )
        client.complete_json("s", "u")
        client.complete_json("s", "u")
        assert len(client.usage_log) == 2
