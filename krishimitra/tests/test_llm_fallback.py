import pytest

from app.ai.llm.base import LLMProvider, LLMRequest, ProviderError
from app.ai.llm.router import AllProvidersFailed, LLMRouter


class Fake(LLMProvider):
    def __init__(self, name, outcomes, configured=True):
        self.name, self.outcomes, self.configured, self.calls = name, list(outcomes), configured, 0

    def is_configured(self):
        return self.configured

    def generate(self, req, timeout):
        self.calls += 1
        o = self.outcomes.pop(0) if self.outcomes else "ok"
        if isinstance(o, Exception):
            raise o
        return f"{self.name}:{o}"


REQ = LLMRequest(system="s", messages=[{"role": "user", "content": "hi"}])
RETRY = ProviderError("t", retryable=True, kind="timeout")
FATAL = ProviderError("auth", retryable=False, kind="http_401")


def mk(providers, **kw):
    return LLMRouter(providers, max_retries=kw.get("retries", 1), cooldown_seconds=60, sleep=lambda s: None, clock=kw.get("clock", lambda: 0.0))


def test_groq_ok_uses_only_groq():
    g, m, ge = Fake("groq", ["a"]), Fake("mistral", []), Fake("gemini", [])
    r = mk([g, m, ge]).generate(REQ)
    assert r.provider == "groq" and m.calls == 0 and ge.calls == 0


def test_groq_fails_falls_to_mistral():
    g, m = Fake("groq", [FATAL]), Fake("mistral", ["x"])
    r = mk([g, m, Fake("gemini", [])]).generate(REQ)
    assert r.provider == "mistral" and g.calls == 1          # non-retryable: no retry
    assert [a["provider"] for a in r.attempts] == ["groq", "mistral"]


def test_groq_and_mistral_fail_falls_to_gemini():
    r = mk([Fake("groq", [FATAL]), Fake("mistral", [FATAL]), Fake("gemini", ["g"])]).generate(REQ)
    assert r.provider == "gemini"


def test_retry_only_on_retryable_and_bounded():
    g = Fake("groq", [RETRY, RETRY, RETRY])
    with pytest.raises(AllProvidersFailed):
        mk([g], retries=1).generate(REQ)
    assert g.calls == 2                                         # 1 + exactly 1 retry, no loops


def test_retry_then_success_same_provider():
    g = Fake("groq", [RETRY, "ok"])
    assert mk([g]).generate(REQ).provider == "groq" and g.calls == 2


def test_all_fail_raises_with_attempts():
    with pytest.raises(AllProvidersFailed) as e:
        mk([Fake("groq", [FATAL]), Fake("mistral", [FATAL]), Fake("gemini", [FATAL])]).generate(REQ)
    assert len(e.value.attempts) == 3


def test_circuit_breaker_cooldown_skips_unhealthy_provider():
    t = {"now": 0.0}
    g, m = Fake("groq", [FATAL, "late"]), Fake("mistral", ["a", "b", "c"])
    r = mk([g, m], clock=lambda: t["now"])
    r.generate(REQ)
    assert r.generate(REQ).provider == "mistral" and g.calls == 1     # groq skipped while cooling down
    t["now"] = 61
    assert r.generate(REQ).provider == "groq"                         # recovers after cooldown


def test_unconfigured_provider_skipped():
    r = mk([Fake("groq", [], configured=False), Fake("mistral", ["m"])]).generate(REQ)
    assert r.provider == "mistral" and r.attempts[0]["error_kind"] == "not_configured"


def test_provider_errors_do_not_leak_body_or_key():
    from app.ai.llm import providers
    import httpx
    resp = httpx.Response(401, text="secret-key-sk-123 echoed prompt")
    with pytest.raises(ProviderError) as e:
        providers._raise_for(resp)
    assert "secret" not in str(e.value) and "sk-123" not in str(e.value)


def test_log_formatter_redacts_secrets():
    import logging
    from app.core.logging import JsonFormatter
    rec = logging.LogRecord("x", logging.INFO, "", 0, "calling with api_key=sk-abc Authorization: Bearer zzz", None, None)
    out = JsonFormatter().format(rec)
    assert "sk-abc" not in out
