"""Provider adapters calling each vendor's documented HTTP API with httpx.

Models and keys come from environment variables; model IDs are never hardcoded in logic.
"""
import httpx

from app.ai.llm.base import LLMProvider, LLMRequest, ProviderError

RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


def _raise_for(resp: httpx.Response) -> None:
    if resp.status_code < 400:
        return
    retry = resp.status_code in RETRYABLE_STATUS
    # Never include response body: it may echo prompts.
    raise ProviderError(f"HTTP {resp.status_code}", retryable=retry, kind=f"http_{resp.status_code}")


class _OpenAICompat(LLMProvider):
    url = ""

    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)

    def generate(self, req: LLMRequest, timeout: float) -> str:
        body = {"model": self.model, "temperature": req.temperature, "max_tokens": req.max_tokens,
                "messages": [{"role": "system", "content": req.system}, *req.messages]}
        try:
            r = httpx.post(self.url, json=body, headers={"Authorization": f"Bearer {self.api_key}"}, timeout=timeout)
        except httpx.TimeoutException:
            raise ProviderError("timeout", retryable=True, kind="timeout")
        except httpx.HTTPError:
            raise ProviderError("network", retryable=True, kind="network")
        _raise_for(r)
        try:
            return r.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            raise ProviderError("bad response shape", retryable=False, kind="bad_response")


class GroqProvider(_OpenAICompat):
    name = "groq"
    url = "https://api.groq.com/openai/v1/chat/completions"


class MistralProvider(_OpenAICompat):
    name = "mistral"
    url = "https://api.mistral.ai/v1/chat/completions"


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key, self.model = api_key, model

    def is_configured(self) -> bool:
        return bool(self.api_key and self.model)

    def generate(self, req: LLMRequest, timeout: float) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
        contents = [{"role": "user" if m["role"] == "user" else "model", "parts": [{"text": m["content"]}]} for m in req.messages]
        body = {"systemInstruction": {"parts": [{"text": req.system}]}, "contents": contents,
                "generationConfig": {"temperature": req.temperature, "maxOutputTokens": req.max_tokens}}
        try:
            r = httpx.post(url, json=body, headers={"x-goog-api-key": self.api_key}, timeout=timeout)
        except httpx.TimeoutException:
            raise ProviderError("timeout", retryable=True, kind="timeout")
        except httpx.HTTPError:
            raise ProviderError("network", retryable=True, kind="network")
        _raise_for(r)
        try:
            return "".join(p["text"] for p in r.json()["candidates"][0]["content"]["parts"]).strip()
        except Exception:
            raise ProviderError("bad response shape or blocked", retryable=False, kind="bad_response")
