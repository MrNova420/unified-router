import pytest

from unified_router.provider import (
    BaseProvider,
    RateLimitError,
    ProviderError,
    AuthError,
    ModelNotFoundError,
)


class DummyProvider(BaseProvider):
    name: str = "dummy"

    async def fetch_models(self, client):
        return [{"id": "test-model"}]

    async def chat(self, client, model, messages, **kwargs):
        return {"choices": [{"message": {"content": "ok"}}]}


def test_provider_initialization():
    p = DummyProvider({"api_key": "test_key", "base_url": "http://test"})
    assert p.is_configured
    assert p.api_key == "test_key"
    assert p.circuit_breaker.name == "dummy"


def test_provider_unconfigured():
    p = DummyProvider({})
    assert not p.is_configured
    assert not p.is_available


def test_mask_api_key():
    p = DummyProvider({"api_key": "verysecretkey123"})
    masked = p.mask_api_key()
    assert masked.startswith("very") and masked.endswith("123")
    assert "****" in masked


def test_mark_rate_limited():
    p = DummyProvider({"api_key": "k"})
    p.mark_rate_limited(retry_after=10)
    assert p.is_rate_limited
    assert p.consecutive_failures == 1


def test_rate_limit_error_with_retry_after():
    e = RateLimitError("Too many requests", retry_after=120)
    assert e.retry_after == 120


def test_provider_error_status_code():
    e = ProviderError("Bad request", status_code=400)
    assert e.status_code == 400


def test_health_status_structure():
    p = DummyProvider({"api_key": "k"})
    status = p.health_status()
    assert "circuit_state" in status
    assert status["configured"]
    assert status["name"] == "dummy"
