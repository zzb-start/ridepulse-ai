"""LLM 客户端 — OpenAI GPT-6 系列（chat/completions）。

实现要求：
1. Base URL / 模型名由环境变量指定，默认指向 OpenAI 官方端点
2. 按模型能力构造请求体：GPT-6 系列不接受 temperature / top_p，
   推理强度走 reasoning_effort（low / medium / high / xhigh / max，无 none）
3. 超时，最多重试 3 次（仅超时/限流/5xx）；不支持的参数按服务端报错一次性剔除后重试
4. 结构化 JSON 输出
5. JSON 解析失败只允许一次修复调用
6. 第二次仍失败进入人工队列，不生成猜测结果
7. 测试使用 Fake 客户端，不消耗真实 API
8. 记录模型名/耗时/token/推理 token，不记录 Secret
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"

REPAIR_SYSTEM_PROMPT = (
    "你是JSON修复器。下面文本是模型输出的JSON，无法解析。"
    "请只输出修正后的合法JSON对象，不要包含任何解释、前缀或Markdown代码块标记。"
)


class LLMClientError(Exception):
    """LLM 调用失败。"""


@dataclass(frozen=True)
class ModelCapabilities:
    """单个模型在 chat/completions 上的参数能力。

    GPT-6 起采样参数（temperature / top_p / logprobs）已从推理模型上移除，
    继续传会直接报错；推理强度也不再接受 none / minimal。
    """

    supports_temperature: bool
    supports_reasoning_effort: bool
    reasoning_efforts: tuple[str, ...] = ()


# GPT-6 全系：无采样参数，推理强度五档
_GPT6 = ModelCapabilities(
    supports_temperature=False,
    supports_reasoning_effort=True,
    reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
)
# 上一代推理模型（o 系列 / GPT-5）：同样不接受采样参数
_REASONING_LEGACY = ModelCapabilities(
    supports_temperature=False,
    supports_reasoning_effort=True,
    reasoning_efforts=("minimal", "low", "medium", "high"),
)
# 常规对话模型与第三方 OpenAI 兼容端点
_STANDARD = ModelCapabilities(
    supports_temperature=True,
    supports_reasoning_effort=False,
)


def capabilities_for(model: str) -> ModelCapabilities:
    """按模型名判定参数能力（大小写不敏感）。"""
    name = (model or "").strip().lower()
    if name.startswith("gpt-6"):
        return _GPT6
    if name.startswith(("o1", "o3", "o4", "gpt-5")):
        return _REASONING_LEGACY
    return _STANDARD


def resolve_reasoning_effort(model: str, effort: str | None) -> str | None:
    """把配置的推理强度收敛到该模型支持的档位。

    模型不支持推理强度时返回 None（不发该字段）；
    配置值非法时降级到 low —— 官方建议从 low 起步，而不是假设旧档位等价。
    """
    caps = capabilities_for(model)
    if not caps.supports_reasoning_effort or not effort:
        return None
    value = effort.strip().lower()
    if value in caps.reasoning_efforts:
        return value
    if value in {"none", "minimal"}:
        logger.warning(
            "模型 %s 不支持推理强度 %s，已按 low 下发（GPT-6 起取消 none/minimal）",
            model, value,
        )
    else:
        logger.warning(
            "模型 %s 不支持推理强度 %s（可选 %s），已按 low 下发",
            model, value, "/".join(caps.reasoning_efforts),
        )
    return "low"


class BaseLLMClient:
    """LLM 客户端基类 — OpenAI chat/completions 接口（GPT-6 参数自适应）。"""

    def __init__(self, *, base_url: str, api_key: str, model: str,
                 timeout_seconds: int = 60, max_retries: int = 3,
                 reasoning_effort: str | None = None,
                 transport: httpx.BaseTransport | None = None,
                 backoff_base: float = 0.5) -> None:
        self.base_url = (base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.reasoning_effort = resolve_reasoning_effort(model, reasoning_effort)
        self.capabilities = capabilities_for(model)
        self.backoff_base = backoff_base
        self.usage_log: list[dict[str, Any]] = []
        # 服务端拒绝过的参数（按模型记住，后续请求不再发送）
        self._dropped_params: set[str] = set()
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

    def build_payload(self, system: str, user: str, temperature: float,
                      response_format: dict | None) -> dict[str, Any]:
        """按模型能力构造请求体。

        GPT-6 系列不发送 temperature（会直接报错），改用 reasoning_effort 控制
        推理深度；提示词里已经约束了输出风格，不依赖采样温度。
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if self.capabilities.supports_temperature and "temperature" not in self._dropped_params:
            payload["temperature"] = temperature
        if self.reasoning_effort and "reasoning_effort" not in self._dropped_params:
            payload["reasoning_effort"] = self.reasoning_effort
        if response_format and "response_format" not in self._dropped_params:
            payload["response_format"] = response_format
        return payload

    @staticmethod
    def _rejected_param(resp: httpx.Response) -> str | None:
        """从 400 响应里取出被拒绝的参数名（OpenAI 错误体带 param 字段）。"""
        try:
            body = resp.json()
        except ValueError:
            return None
        error = body.get("error") if isinstance(body, dict) else None
        if not isinstance(error, dict):
            return None
        param = error.get("param")
        return param if isinstance(param, str) and param else None

    def _call_with_retries(self, system: str, user: str, temperature: float,
                           response_format: dict | None) -> tuple[str, dict]:
        """带重试的 HTTP 调用，返回 (content, usage)，并记录 usage_log。"""
        start = time.perf_counter()
        attempts = 0
        negotiated = 0
        while True:
            attempts += 1
            try:
                payload = self.build_payload(system, user, temperature, response_format)
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
                if status == 400 and negotiated < 2:
                    # 参数不被该模型接受（如旧模型传 reasoning_effort、新模型传 temperature）：
                    # 剔除后重试一次，并记住该模型不吃这个参数
                    rejected = self._rejected_param(resp)
                    if rejected and rejected in payload:
                        logger.warning(
                            "模型 %s 不接受参数 %s，本次请求剔除后重试", self.model, rejected
                        )
                        self._dropped_params.add(rejected)
                        negotiated += 1
                        attempts -= 1  # 参数协商不计入重试预算
                        continue
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
                if not content:
                    raise LLMClientError("LLM 返回空内容（可能被内容策略拦截）")
                self._log_success(start, attempts, usage, data.get("model"))
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

        推理模型偶尔会在正文前输出 <think>…</think> 或 <reasoning>…</reasoning>；
        残余的前后缀文本也一并兜底剥离。
        """
        text = content.strip()
        # 去掉思考块前缀（可能跨行）
        text = re.sub(r"<think>.*?</think>\s*", "", text, flags=re.DOTALL)
        text = re.sub(r"<reasoning>.*?</reasoning>\s*", "", text, flags=re.DOTALL)
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

    def _log_success(self, start: float, attempts: int, usage: dict,
                     response_model: str | None = None) -> None:
        """记录成功调用（不含任何 Secret）。

        response_model 与请求模型不一致时单独留痕：中转端点静默映射模型是常见坑，
        记录实际回包模型才能事后追责。
        """
        details = usage.get("completion_tokens_details") or {}
        entry = {
            "model": self.model,
            "response_model": response_model or self.model,
            "reasoning_effort": self.reasoning_effort,
            "status": "success",
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "reasoning_tokens": details.get("reasoning_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
            "duration_ms": int((time.perf_counter() - start) * 1000),
            "attempts": attempts,
        }
        self.usage_log.append(entry)
        if response_model and response_model != self.model:
            logger.warning(
                "模型回包不一致: 请求 %s 实际返回 %s（端点可能做了静默映射）",
                self.model, response_model,
            )
        logger.info(
            "LLM 调用成功: model=%s effort=%s status=success total_tokens=%s",
            self.model, self.reasoning_effort, entry["total_tokens"],
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


def probe_endpoint(*, base_url: str, api_key: str, models: dict[str, str],
                   reasoning_effort: str | None = None,
                   timeout_seconds: int = 30) -> dict[str, Any]:
    """连通性自检：查 /models 清单 + 用分类模型发一次最小调用。

    第三级验证（真发一次请求并核对回包 model 字段）才是关键：
    清单里有 ≠ 真能调，有的端点会把不存在的模型名静默映射到别的模型上，
    返回照常 200，只有比对回包模型名才能发现。

    models: {"classify": ..., "review": ..., "evidence": ...}
    """
    base = (base_url or DEFAULT_OPENAI_BASE_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {api_key}"}
    primary = models.get("classify", "")
    with httpx.Client(timeout=timeout_seconds) as http:
        listed: list[str] = []
        resp = http.get(f"{base}/models", headers=headers)
        if resp.status_code == 200:
            try:
                listed = [str(item.get("id", "")) for item in resp.json().get("data", [])]
            except (ValueError, AttributeError, TypeError):
                listed = []

        probe = BaseLLMClient(
            base_url=base, api_key=api_key, model=primary,
            timeout_seconds=timeout_seconds, max_retries=1,
            reasoning_effort=reasoning_effort,
        )
        payload = probe.build_payload("你是连通性探针。", "只回复 OK 两个字符。", 0.0, None)
        effort = probe.reasoning_effort
        probe.close()
        resp = http.post(f"{base}/chat/completions", headers=headers, json=payload)

    if resp.status_code != 200:
        raise LLMClientError(f"LLM 自检失败（HTTP {resp.status_code}）: {resp.text[:200]}")
    try:
        body = resp.json()
        served = str(body.get("model") or "")
        content = body["choices"][0]["message"]["content"] or ""
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMClientError(f"LLM 自检响应格式异常: {resp.text[:200]}") from exc
    # 回包模型名可能带日期快照后缀（如 gpt-6-luna-2026-09-22），前缀一致即视为同一模型
    if served and not served.startswith(primary):
        raise LLMClientError(
            f"模型回包不一致：请求 {primary}，实际返回 {served}"
            "（端点可能把不存在的模型名静默映射到其他模型）"
        )
    missing = [name for name in models.values() if listed and name not in listed]
    return {
        "ok": True,
        "base_url": base,
        "models": models,
        "reasoning_effort": effort,
        "served_model": served,
        "listed_count": len(listed),
        "missing_from_list": missing,
        "probe_reply": content[:40],
    }
