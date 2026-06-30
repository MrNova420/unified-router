import asyncio
import time
import pytest

from unified_router.circuit_breaker import CircuitBreaker, CircuitState


def test_starts_closed():
    cb = CircuitBreaker("test")
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


def test_opens_after_threshold():
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout=1.0)
    for _ in range(3):
        cb._record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.is_open


def test_half_open_after_recovery_timeout():
    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=0.1)
    cb._record_failure()
    cb._record_failure()
    assert cb.state == CircuitState.OPEN
    time.sleep(0.15)


def test_success_resets():
    cb = CircuitBreaker("test", failure_threshold=2, recovery_timeout=1.0)
    cb._record_failure()
    cb._record_failure()
    assert cb.state == CircuitState.OPEN
    cb._record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_call_success():
    cb = CircuitBreaker("test", failure_threshold=3)

    async def ok_coro():
        return "ok"

    result = await cb.call(ok_coro)
    assert result == "ok"
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_call_failure_opens_circuit():
    cb = CircuitBreaker("test", failure_threshold=2)

    async def fail_coro():
        raise ValueError("fail")

    for _ in range(2):
        with pytest.raises(ValueError):
            await cb.call(fail_coro)
    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_open_circuit_rejects():
    cb = CircuitBreaker("test", failure_threshold=1, recovery_timeout=10.0)

    async def fail_coro():
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await cb.call(fail_coro)
    assert cb.state == CircuitState.OPEN

    with pytest.raises(Exception, match="Circuit breaker OPEN"):
        await cb.call(asyncio.sleep(0))
