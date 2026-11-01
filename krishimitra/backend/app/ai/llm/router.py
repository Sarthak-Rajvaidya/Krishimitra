"""Ordered fallback with per-provider cooldown (circuit breaker) and bounded retries."""
import logging
import time
from typing import Callable

from app.ai.llm.base import LLMProvider, LLMRequest, LLMResponse, ProviderError
from app.core.config import get_settings

log = logging.getLogger("llm")


class AllProvidersFailed(Exception):
    def __init__(self, attempts: list[dict]):
        super().__init__("All LLM providers failed")
        self.attempts = attempts


class LLMRouter:
    def __init__(self, providers: list[LLMProvider], timeout: float = 20, max_retries: int = 1,
                 cooldown_seconds: int = 60, clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep):
        self.providers, self.timeout, self.max_retries = providers, timeout, max_retries
        self.cooldown, self.clock, self.sleep = cooldown_seconds, clock, sleep
        self._down_until: dict[str, float] = {}
        self.stats: dict[str, dict] = {p.name: {"calls": 0, "ok": 0, "last_error": None, "last_latency_ms": None}
                                       for p in providers}

    def status(self) -> list[dict]:
        now = self.clock()
        return [{"provider": p.name, "configured": p.is_configured(),
                 "cooling_down": self._down_until.get(p.name, 0) > now, **self.stats[p.name]} for p in self.providers]

    def generate(self, req: LLMRequest) -> LLMResponse:
        attempts: list[dict] = []
        for p in self.providers:
            if not p.is_configured():
                attempts.append({"provider": p.name, "ok": False, "latency_ms": 0, "error_kind": "not_configured"})
                continue
            if self._down_until.get(p.name, 0) > self.clock():
                attempts.append({"provider": p.name, "ok": False, "latency_ms": 0, "error_kind": "cooldown"})
                continue
            for attempt in range(self.max_retries + 1):
                t0 = time.perf_counter()
                try:
                    text = p.generate(req, self.timeout)
                    ms = int((time.perf_counter() - t0) * 1000)
                    st = self.stats[p.name]
                    st["calls"] += 1; st["ok"] += 1; st["last_latency_ms"] = ms
                    attempts.append({"provider": p.name, "ok": True, "latency_ms": ms, "error_kind": None})
                    return LLMResponse(text=text, provider=p.name, model=getattr(p, "model", ""), latency_ms=ms, attempts=attempts)
                except ProviderError as ex:
                    ms = int((time.perf_counter() - t0) * 1000)
                    st = self.stats[p.name]
                    st["calls"] += 1; st["last_error"] = ex.kind; st["last_latency_ms"] = ms
                    attempts.append({"provider": p.name, "ok": False, "latency_ms": ms, "error_kind": ex.kind})
                    log.warning("llm provider=%s failed kind=%s", p.name, ex.kind)
                    if ex.retryable and attempt < self.max_retries:
                        self.sleep(min(0.5 * (attempt + 1), 2))
                        continue
                    self._down_until[p.name] = self.clock() + self.cooldown  # trip breaker
                    break
        raise AllProvidersFailed(attempts)


_router: LLMRouter | None = None


def build_router() -> LLMRouter:
    from app.ai.llm.providers import GeminiProvider, GroqProvider, MistralProvider
    s = get_settings()
    reg = {"groq": GroqProvider(s.groq_api_key, s.groq_model), "mistral": MistralProvider(s.mistral_api_key, s.mistral_model),
           "gemini": GeminiProvider(s.gemini_api_key, s.gemini_model)}
    order = [reg[n.strip()] for n in s.llm_provider_order.split(",") if n.strip() in reg]
    return LLMRouter(order, s.llm_timeout_seconds, s.llm_max_retries, s.llm_cooldown_seconds)


def get_router() -> LLMRouter:
    global _router
    if _router is None:
        _router = build_router()
    return _router


def set_router(r: LLMRouter | None) -> None:  # used by tests
    global _router
    _router = r
