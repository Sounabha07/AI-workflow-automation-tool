"""LLM providers behind one interface. Adding a provider: implement
LLMProvider in its own module and add it to PROVIDERS; the block's
`provider` options are generated from this dict."""

from app.llm.base import LLMProvider
from app.llm.gemini import GeminiProvider

PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiProvider,
}

DEFAULT_PROVIDER = "gemini"

PROVIDER_LABELS: dict[str, str] = {
    "gemini": "Google Gemini",
}
