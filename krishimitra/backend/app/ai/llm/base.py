from dataclasses import dataclass, field


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool = False, kind: str = "error"):
        super().__init__(message)
        self.retryable = retryable
        self.kind = kind


@dataclass
class LLMRequest:
    system: str
    messages: list[dict]            # [{"role": "user"|"assistant", "content": str}]
    max_tokens: int = 700
    temperature: float = 0.2


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    latency_ms: int
    attempts: list[dict] = field(default_factory=list)  # [{"provider","ok","latency_ms","error_kind"}]


class LLMProvider:
    name = "base"

    def is_configured(self) -> bool:
        raise NotImplementedError

    def generate(self, req: LLMRequest, timeout: float) -> str:
        raise NotImplementedError
