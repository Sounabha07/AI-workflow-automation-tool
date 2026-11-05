"""LLM providers behind one interface. Adding a provider: implement
LLMProvider in its own module and add it to PROVIDERS; the block's
`provider` options are generated from this dict.

The scripted test provider is added only when ENABLE_TEST_PROVIDERS=1
(CI and the smoke test); it is unavailable otherwise."""

import os

from app.llm.base import LLMProvider
from app.llm.gemini import GeminiProvider
from app.llm.scripted import ScriptedProvider

TEST_PROVIDERS_ENV = "ENABLE_TEST_PROVIDERS"


def test_providers_enabled() -> bool:
    return os.environ.get(TEST_PROVIDERS_ENV, "").strip() == "1"


PROVIDERS: dict[str, type[LLMProvider]] = {
    "gemini": GeminiProvider,
}

PROVIDER_LABELS: dict[str, str] = {
    "gemini": "Google Gemini",
}

if test_providers_enabled():
    PROVIDERS["scripted"] = ScriptedProvider
    PROVIDER_LABELS["scripted"] = "Scripted (test only)"

DEFAULT_PROVIDER = "gemini"
