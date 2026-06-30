import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from unified_router.router import Router
from unified_router.provider import BaseProvider, RateLimitError, ProviderError, AuthError

class MockProvider(BaseProvider):
    def __init__(self, name, models=None, behavior="ok", retry_after=60):
        super().__init__({"api_key": "test-key"})
        self.name = name
        self.models = models or ["model-1"]
        self.behavior = behavior
        self.retry_after = retry_after
        self.call_count = 0

    async def fetch_models(self, client):
        return [{"id": m} for m in self.models]

    async def chat(self, client, model, messages, **kwargs):
        self.call_count += 1
        if self.behavior == "ok":
            return {"choices": [{"message": {"content": "ok"}}]}
        elif self.behavior == "rate_limit":
            self.mark_rate_limited(self.retry_after)
            raise RateLimitError(f"{self.name} rate limited", retry_after=self.retry_after)
        elif self.behavior == "error":
            self.mark_error()
            raise ProviderError(f"{self.name} error")
        elif self.behavior == "auth_error":
            raise AuthError(f"{self.name} unauthorized")
        raise Exception("Unexpected behavior")

    async def stream(self, client, model, messages, **kwargs):
        if self.behavior == "ok":
            yield b"data: chunk\n\n"
            yield b"data: [DONE]\n\n"
        else:
            raise RateLimitError(f"{self.name} rate limited", retry_after=self.retry_after)

@pytest.fixture
def router():
    providers = {
        "p1": MockProvider("p1", models=["m1", "m2"], behavior="ok"),
        "p2": MockProvider("p2", models=["m1", "m3"], behavior="ok"),
    }
    return Router(
        providers=providers,
        priority=["p1", "p2"],
        strategy="priority",
    )

@pytest.mark.asyncio
async def test_route_success_first_try(router):
    result = await router.route(model="m1", messages=[{"role": "user", "content": "hi"}])
    assert result["choices"][0]["message"]["content"] == "ok"
    assert router.providers["p1"].call_count == 1

@pytest.mark.asyncio
async def test_route_fallback_on_rate_limit(router):
    router.providers["p1"].behavior = "rate_limit"
    router.providers["p1"].retry_after = 1
    
    result = await router.route(model="m1", messages=[{"role": "user", "content": "hi"}])
    assert result["choices"][0]["message"]["content"] == "ok"
    assert router.providers["p1"].call_count == 1
    assert router.providers["p2"].call_count == 1

@pytest.mark.asyncio
async def test_route_auto_traversal(router):
    # Mock sleep to make test fast
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        # P1 has m1, m2. P2 has m1, m3.
        # Make P1 fail for everything
        router.providers["p1"].behavior = "error"
        
        result = await router.route_auto(messages=[{"role": "user", "content": "hi"}])
        assert result["_auto_provider"] == "p2"
        # P1 should have been tried for m1 and m2 before moving to P2
        assert router.providers["p1"].call_count >= 2

@pytest.mark.asyncio
async def test_circuit_breaker_integration(router):
    router.providers["p1"].behavior = "error"
    # Trigger circuit open (threshold=5)
    for _ in range(6):
        try:
            await router.route(model="m1", messages=[{"role": "user", "content": "hi"}])
        except:
            pass
    
    assert router.providers["p1"].circuit_open
    
    # Next request should skip P1 immediately
    router.providers["p1"].behavior = "ok"
    await router.route(model="m1", messages=[{"role": "user", "content": "hi"}])
    # P1 should not have been called again because circuit is open
    assert router.providers["p1"].call_count == 5
