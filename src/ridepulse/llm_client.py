"""LLM 客户端 — OpenAI 兼容接口。

实现要求：
1. Base URL / 模型名由环境变量指定
2. 温度默认 0，超时，最多重试 3 次（仅超时/限流/5xx）
3. 结构化 JSON 输出
4. JSON 解析失败只允许一次修复调用
5. 第二次仍失败进入人工队列，不生成猜测结果
6. 测试使用 Fake 客户端，不消耗真实 API
7. 记录模型名/耗时/token，不记录 Secret
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

REPAIR_SYSTEM_PROMPT = (
    "你是JSON修复器。下面文本是模型输出的JSON，无法解析。"
    "请只输出修正后的合法JSON对象，不要包含任何解释、前缀或Markdown代码块标记。"
)


class LLMClientError(Exception):
    """LLM 调用失败。"""


class BaseLLMClient:
    """LLM 客户端基类 — OpenAI 兼容 chat/completions 接口。"""

    def __init__(self, *, base_url: str, api_key: str, model: str,
                 timeout_seconds: int = 60, max_retries: int = 3,
                 transport: httpx.BaseTransport | None = None,
                 backoff_base: float = 0.5) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.usage_log: list[dict[str, Any]] = []
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            transport=transport,
        )

    def close(self) -> None:
        """关闭底层 HTTP 客户端。"""
        self._client.close()

    # ----------------------------------------------------------
    # 对外接口
    # ----------------------------------------------------------

    def complete_json(self, system: str, user: str, *,
                      temperature: float = 0.0,
                      response_format: dict | None = None) -> dict[str, Any]:
        """调用模型并返回结构化 JSON。

        解析失败时允许一次修复调用；仍失败抛 LLMClientError（上层进入人工队列），
        绝不生成猜测结果。
        """
        response_format = {"type": "json_object"} if response_format is None else response_format
        content, _ = self._call_with_retries(system, user, temperature, response_format)
        try:
            return self._parse_json(content)
        except ValueError as exc:
            logger.warning("LLM 输出 JSON 解析失败，执行一次修复调用")
            repair_user = f"无法解析的内容：\n{content}"
            content, _ = self._call_with_retries(
                REPAIR_SYSTEM_PROMPT, repair_user, temperature, response_format
            )
            try:
                return self._parse_json(content)
            except ValueError:
                raise LLMClientError("JSON 解析失败（修复调用后仍失败），进入人工队列") from exc

    # ----------------------------------------------------------
    # 内部实现
    # ----------------------------------------------------------

    def _call_with_retries(self, system: str, user: str, temperature: float,
                           response_format: dict | None) -> tuple[str, dict]:
        """带重试的 HTTP 调用，返回 (content, usage)，并记录 usage_log。"""
        start = time.perf_counter()
        attempts = 0
        while True:
            attempts += 1
            try:
                payload = {
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "temperature": temperature,
                    "response_format": response_format,
                }
                if "minimax" in self.base_url:
                    # MiniMax M 系列默认开自适应思考：响应慢且带 <think> 前缀
                    # （2026-08-16 实测 10.5s vs 关闭后 2.2s）。其他供应商不受影响。
                    payload["thinking"] = {"type": "disabled"}
                resp = self._client.post(
                    "/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                status = resp.status_code
                # 只对限流(429)和服务端错误(5xx)重试
                if status == 429 or status >= 500:
                    if attempts <= self.max_retries:
                        self._backoff(attempts)
                        continue
                    raise LLMClientError(f"LLM 服务错误（HTTP {status}），重试耗尽")
                if status >= 400:
                    raise LLMClientError(
                        f"LLM 请求被拒绝（HTTP {status}）: {resp.text[:200]}"
                    )
                try:
                    data = resp.json()
                    content = data["choices"][0]["message"]["content"]
                    usage = data.get("usage") or {}
                except (ValueError, KeyError, IndexError, TypeError) as exc:
                    raise LLMClientError("LLM 响应格式异常") from exc
                self._log_success(start, attempts, usage)
                return content, usage
            except (httpx.TimeoutException, httpx.RequestError) as exc:
                # 超时与连接中断（含 Server disconnected）都按临时故障重试
                if attempts <= self.max_retries:
                    self._backoff(attempts)
                    continue
                if isinstance(exc, httpx.TimeoutException):
                    self._log_failure(start, attempts, "timeout")
                    raise LLMClientError(
                        f"LLM 调用超时（{self.timeout_seconds}s）"
                    ) from exc
                self._log_failure(start, attempts, "connection_error")
                raise LLMClientError(f"LLM 连接失败: {exc}") from exc
            except LLMClientError:
                self._log_failure(start, attempts, "http_error")
                raise

    def _backoff(self, attempts: int) -> None:
        """指数退避，封顶 5 秒。"""
        time.sleep(min(self.backoff_base * (2 ** (attempts - 1)), 5.0))

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        """解析模型输出的 JSON，容忍 Markdown 代码块与思考块前缀。

        部分模型（如 MiniMax M3 自适应思考模式）会在正文前输出
        <think>...</think>；残余的前后缀文本也一并兜底剥离。
        """
        text = content.strip()
        # 去掉思考块前缀（<think>…</think>，可能跨行）
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                return parsed
        except ValueError:
            pass
        # 兜底：截取首个 { 到末个 } 之间的 JSON 片段（容忍残余前后缀文本）
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            parsed = json.loads(text[start:end + 1])
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("JSON 顶层不是对象")

    def _log_success(self, start: float, attempts: int, usage: dict) -> None:
        """记录成功调用（不含任何 Secret）。"""
        entry = {
            "model": self.model,
            "status": "success",
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "duration_ms": int((time.perf_counter() - start) * 1000),
            "attempts": attempts,
        }
        self.usage_log.append(entry)
        logger.info(
            "LLM 调用成功: model=%s status=success total_tokens=%s",
            self.model, entry["total_tokens"],
        )

    def _log_failure(self, start: float, attempts: int, error_type: str) -> None:
        """记录失败调用（不含任何 Secret）。"""
        entry = {
            "model": self.model,
            "status": "failed",
            "error": error_type,
            "duration_ms": int((time.perf_counter() - start) * 1000),
            "attempts": attempts,
        }
        self.usage_log.append(entry)
        logger.warning(
            "LLM 调用失败: model=%s status=failed error=%s", self.model, error_type,
        )


class FakeLLMClient(BaseLLMClient):
    """测试用假客户端 — 不消耗 API。"""

    def __init__(self, responder=None, **kwargs: Any) -> None:
        super().__init__(base_url="fake", api_key="fake", model="fake-model", **kwargs)
        self.responder = responder
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append((system, user))
        if self.responder is None:
            raise LLMClientError("FakeLLMClient 未配置 responder")
        return self.responder(system, user)
