from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import Any, AsyncIterator

import httpx

from .circuit_breaker import CircuitBreaker, CircuitState
from .observability import new_trace, current_trace, record_attempt
from .provider import RateLimitError, ProviderError, AuthError, BaseProvider

logger = logging.getLogger(__name__)

MAX_RETRY_PER_MODEL = 6
RETRY_FALLBACK_DELAYS = [5, 10, 20, 40, 60, 120]
RETRY_AFTER_CAP = 300


def _cache_key(model: str, messages: list, kwargs: dict) -> str:
    payload = json.dumps(
        {"model": model, "messages": messages, "k": {k: v for k, v in kwargs.items() if v is not None}},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _compute_wait(attempt: int, retry_after: int | None = None) -> float:
    if retry_after is not None and retry_after > 0:
        return min(retry_after, RETRY_AFTER_CAP)
    if attempt < len(RETRY_FALLBACK_DELAYS):
        return RETRY_FALLBACK_DELAYS[attempt]
    return RETRY_FALLBACK_DELAYS[-1]


class Router:
    def __init__(
        self,
        providers: dict[str, BaseProvider],
        priority: list[str],
        strategy: str = "priority",
        model_pinning: dict[str, str] | None = None,
        enable_cache: bool = False,
        cache_ttl: int = 3600,
        load_balance_weights: dict[str, int] | None = None,
    ):
        self.providers = providers
        self.priority = priority
        self.strategy = strategy
        self.model_pinning = model_pinning or {}
        self.enable_cache = enable_cache
        self.cache_ttl = cache_ttl
        self.load_balance_weights = load_balance_weights or {}
        self._all_models: list[dict] = []
        self._provider_models: dict[str, set[str]] = {}
        self._models_last_fetch: float = 0
        self._models_lock = asyncio.Lock()
        self._cache: dict[str, tuple[float, dict]] = {}
        self._cache_hits: int = 0
        self._cache_misses: int = 0
        self._rr_counter: int = 0
        self._request_counter: int = 0
        self._http = httpx.AsyncClient(
            timeout=120,
            limits=httpx.Limits(max_keepalive_connections=50, max_connections=200),
        )

    def get_active_providers(self) -> dict[str, BaseProvider]:
        return {
            name: p
            for name, p in self.providers.items()
            if p.is_available
        }

    async def _fetch_from_provider(self, name: str, prov: BaseProvider) -> list[dict]:
        try:
            return await prov.fetch_models(self._http)
        except Exception as e:
            logger.debug("Failed to fetch models from %s: %s", name, e)
            return []

    async def fetch_all_models(self, force: bool = False) -> list[dict]:
        async with self._models_lock:
            now = time.time()
            if not force and self._all_models and (now - self._models_last_fetch) < 120:
                return self._all_models

            tasks = []
            for name, prov in self.providers.items():
                if prov.is_configured and not prov.circuit_open:
                    tasks.append(self._fetch_from_provider(name, prov))

            results = await asyncio.gather(*tasks)
            seen = set()
            models = []
            provider_models: dict[str, set[str]] = {}
            for name, models_list in zip(
                [n for n, p in self.providers.items() if p.is_configured and not p.circuit_open], results
            ):
                ids = set()
                for m in models_list:
                    mid = m.get("id", "")
                    if mid:
                        ids.add(mid)
                        if mid not in seen:
                            seen.add(mid)
                            models.append(m)
                provider_models[name] = ids

            self._all_models = models
            self._provider_models = provider_models
            self._models_last_fetch = now
            return models

    def _providers_for_model(self, model: str) -> list[str]:
        candidates: list[str] = []
        for name, ids in self._provider_models.items():
            if not ids:
                continue
            if model in ids or any(model in m for m in ids):
                if name in self.providers and self.providers[name].is_available:
                    candidates.append(name)
        return candidates

    def _order_providers(self, candidates: list[str]) -> list[str]:
        active = [c for c in candidates if self.providers[c].is_available]
        if not active:
            return []

        if self.strategy == "round_robin":
            self._rr_counter = (self._rr_counter + 1) % max(len(active), 1)
            start = self._rr_counter % len(active)
            return active[start:] + active[:start]

        if self.strategy == "least_latency":
            return sorted(active, key=lambda n: self.providers[n].latency_ema or 999)

        if self.strategy == "weighted":
            def weight(n: str) -> int:
                return -self.load_balance_weights.get(n, 1)
            return sorted(active, key=weight)

        active_set = set(active)
        return [p for p in self.priority if p in active_set]

    def _model_tokens(self, model: str) -> set[str]:
        import re
        toks = re.split(r"[-/:._]+", model.lower())
        return {t for t in toks if len(t) >= 3}

    def _find_similar_models(self, model: str, exclude: set[str] | None = None) -> list[str]:
        exclude = exclude or {model}
        target = self._model_tokens(model)
        if not target:
            return []
        scored: list[tuple[int, str]] = []
        for m in self._all_models:
            mid = m.get("id", "")
            if mid in exclude:
                continue
            mtoks = self._model_tokens(mid)
            overlap = len(target & mtoks)
            if overlap == 0:
                continue
            scored.append((overlap, mid))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored[:5]]

    async def _try_providers(self, target_model: str, messages: list, kwargs: dict, key: str) -> tuple[dict | None, Exception | None]:
        candidates = self._providers_for_model(target_model)
        ordered = self._order_providers(candidates)
        if not ordered:
            ordered = [
                p for p in self.priority
                if p in self.providers and self.providers[p].is_available
            ]
        last_error: Exception | None = None
        for pname in ordered:
            prov = self.providers.get(pname)
            if not prov or not prov.is_available:
                continue
            try:
                start = time.time()
                logger.info("Routing to %s (model: %s, strategy: %s)", pname, target_model, self.strategy)
                result = await prov.chat(self._http, target_model, messages, **kwargs)
                record_attempt(pname, target_model, "ok", (time.time() - start) * 1000)
                self._set_cache(key, result)
                return result, None
            except (RateLimitError, ProviderError, Exception) as e:
                latency = (time.time() - start) * 1000 if 'start' in dir() else 0
                record_attempt(pname, target_model, "error", latency, str(e))
                last_error = e
                continue
        return None, last_error

    async def _try_providers_stream(self, target_model: str, messages: list, kwargs: dict) -> tuple[AsyncIterator[bytes] | None, Exception | None]:
        candidates = self._providers_for_model(target_model)
        ordered = self._order_providers(candidates)
        if not ordered:
            ordered = [
                p for p in self.priority
                if p in self.providers and self.providers[p].is_available
            ]
        last_error: Exception | None = None
        for pname in ordered:
            prov = self.providers.get(pname)
            if not prov or not prov.is_available:
                continue
            try:
                logger.info("Streaming via %s (model: %s)", pname, target_model)
                stream_iter = prov.stream(self._http, target_model, messages, **kwargs)
                first_chunk: bytes | None = None
                try:
                    first_chunk = await stream_iter.__anext__()
                except StopAsyncIteration:
                    return None, None
                except (RateLimitError, ProviderError) as e:
                    last_error = e
                    record_attempt(pname, target_model, "error", 0, str(e))
                    continue
                except Exception as e:
                    last_error = e
                    record_attempt(pname, target_model, "error", 0, str(e))
                    continue

                async def gen(fc: bytes = first_chunk, si=stream_iter):
                    yield fc
                    async for chunk in si:
                        yield chunk

                return gen(), None
            except (RateLimitError, ProviderError, Exception) as e:
                last_error = e
                record_attempt(pname, target_model, "error", 0, str(e))
                continue
        return None, last_error

    async def _try_cache(self, key: str) -> dict | None:
        if not self.enable_cache:
            return None
        entry = self._cache.get(key)
        if not entry:
            self._cache_misses += 1
            return None
        ts, data = entry
        if time.time() - ts > self.cache_ttl:
            self._cache.pop(key, None)
            self._cache_misses += 1
            return None
        self._cache_hits += 1
        return data

    def _set_cache(self, key: str, data: dict):
        if self.enable_cache:
            self._cache[key] = (time.time(), data)

    async def _call_with_circuit(self, prov: BaseProvider, coro_fn, *args, **kwargs):
        async with prov._semaphore:
            return await prov.circuit_breaker.call(lambda: coro_fn(*args, **kwargs))

    async def route(
        self,
        model: str,
        messages: list,
        **kwargs,
    ) -> dict:
        if not self.providers:
            raise ProviderError("No providers configured")

        trace = current_trace()
        await self.fetch_all_models(force=False)

        key = _cache_key(model, messages, kwargs)
        cached = await self._try_cache(key)
        if cached is not None:
            logger.info("Cache hit for model %s", model)
            if trace:
                trace.cache_hit = True
            return cached

        pinned = self.model_pinning.get(model)
        if pinned and pinned in self.providers:
            prov = self.providers[pinned]
            if prov.is_available:
                logger.info("Pinned model %s -> %s", model, pinned)
                try:
                    result = await self._call_with_circuit(prov, prov.chat, self._http, model, messages, **kwargs)
                    self._set_cache(key, result)
                    return result
                except Exception as e:
                    logger.warning("Pinned provider %s failed: %s", pinned, e)

        candidates = self._providers_for_model(model)
        ordered = self._order_providers(candidates)
        if not ordered:
            ordered = [
                p for p in self.priority
                if p in self.providers and self.providers[p].is_available
            ]

        last_error: Exception | None = None
        for pname in ordered:
            prov = self.providers.get(pname)
            if not prov or not prov.is_available:
                continue

            try:
                logger.info("Routing to %s (model: %s, strategy: %s)", pname, model, self.strategy)
                start = time.time()
                result = await self._call_with_circuit(prov, prov.chat, self._http, model, messages, **kwargs)
                record_attempt(pname, model, "ok", (time.time() - start) * 1000)
                self._set_cache(key, result)
                if trace:
                    trace.final_provider = pname
                    trace.final_model = model
                return result
            except RateLimitError as e:
                wait = _compute_wait(0, e.retry_after)
                logger.warning("%s hit rate limit: %s (waiting %ds)", pname, e, int(wait))
                record_attempt(pname, model, "rate_limit", 0, str(e))
                last_error = e
                continue
            except AuthError as e:
                logger.error("%s auth error (skipping permanently): %s", pname, e)
                record_attempt(pname, model, "auth_error", 0, str(e))
                last_error = e
                continue
            except ProviderError as e:
                logger.warning("%s error: %s", pname, e)
                record_attempt(pname, model, "error", 0, str(e))
                last_error = e
                continue
            except Exception as e:
                logger.error("%s unexpected error: %s", pname, e)
                record_attempt(pname, model, "error", 0, str(e))
                last_error = e
                continue

        logger.warning("All providers failed for model '%s'. Searching similar models...", model)
        similar = self._find_similar_models(model)
        tried: set[str] = {model}
        last_err = last_error
        for alt_model in similar:
            if alt_model in tried:
                continue
            tried.add(alt_model)
            logger.info("Auto-fallback: trying similar model '%s'", alt_model)
            result, last_err = await self._try_providers(alt_model, messages, kwargs, _cache_key(alt_model, messages, kwargs))
            if result is not None:
                result["_fallback_model"] = alt_model
                result["_original_model"] = model
                if trace:
                    trace.final_provider = result.get("_fallback_model")
                    trace.final_model = alt_model
                return result

        raise ProviderError(
            f"All providers and fallback models failed for '{model}'. Last error: {last_err}"
        )

    async def route_stream(
        self,
        model: str,
        messages: list,
        **kwargs,
    ) -> AsyncIterator[bytes]:
        if not self.providers:
            raise ProviderError("No providers configured")

        await self.fetch_all_models(force=False)

        candidates = self._providers_for_model(model)
        ordered = self._order_providers(candidates)
        if not ordered:
            ordered = [
                p for p in self.priority
                if p in self.providers and self.providers[p].is_available
            ]

        last_error: Exception | None = None
        for pname in ordered:
            prov = self.providers.get(pname)
            if not prov or not prov.is_available:
                continue
            try:
                logger.info("Streaming via %s (model: %s)", pname, model)
                async with prov._semaphore:
                    first_chunk = True
                    async for chunk in prov.stream(self._http, model, messages, **kwargs):
                        if first_chunk:
                            first_chunk = False
                        yield chunk
                    return
            except RateLimitError as e:
                wait = _compute_wait(0, e.retry_after)
                logger.warning("%s stream rate limited: %s (waiting %ds)", pname, e, int(wait))
                last_error = e
                continue
            except ProviderError as e:
                logger.warning("%s stream error: %s", pname, e)
                last_error = e
                continue
            except Exception as e:
                logger.error("%s stream unexpected error: %s", pname, e)
                last_error = e
                continue

        logger.warning("All providers failed to stream model '%s'. Searching similar models...", model)
        similar = self._find_similar_models(model)
        tried: set[str] = {model}
        last_err = last_error
        for alt_model in similar:
            if alt_model in tried:
                continue
            tried.add(alt_model)
            logger.info("Stream auto-fallback: trying similar model '%s'", alt_model)
            gen, last_err = await self._try_providers_stream(alt_model, messages, kwargs)
            if gen is not None:
                async for chunk in gen:
                    yield chunk
                return

        raise ProviderError(
            f"All providers and fallback models failed to stream '{model}'. Last error: {last_err}"
        )

    async def _auto_try_provider(
        self, pname: str, prov: BaseProvider, messages: list, kwargs: dict,
    ) -> tuple[dict | None, str | None]:
        if prov.circuit_open:
            logger.info("Auto: skipping %s (circuit breaker open)", pname)
            return None, f"circuit breaker open for {pname}"

        models = self._provider_models.get(pname, set())
        if not models:
            try:
                fetched = await prov.fetch_models(self._http)
                models = {m["id"] for m in fetched if m.get("id")}
            except Exception:
                return None, f"could not fetch models from {pname}"

        model_list = sorted([m for m in models if m])
        if not model_list:
            return None, f"no models available on {pname}"

        last_err: str | None = None
        for model_id in model_list:
            attempt = 0
            while attempt < MAX_RETRY_PER_MODEL:
                if prov.circuit_open:
                    logger.info("Auto: circuit breaker opened for %s, skipping remaining models", pname)
                    return None, f"circuit breaker opened for {pname}"

                try:
                    logger.info(
                        "Auto routing: %s / %s (attempt %d/%d)",
                        pname, model_id, attempt + 1, MAX_RETRY_PER_MODEL,
                    )
                    start = time.time()
                    async with prov._semaphore:
                        result = await prov.chat(self._http, model_id, messages, **kwargs)
                    record_attempt(pname, model_id, "ok", (time.time() - start) * 1000)
                    result["_auto_routed"] = True
                    result["_auto_provider"] = pname
                    result["_auto_model"] = model_id
                    return result, None

                except RateLimitError as e:
                    wait = _compute_wait(attempt, e.retry_after)
                    logger.warning(
                        "Auto: %s / %s rate limited (attempt %d) — waiting %ds (provider said: %ds)",
                        pname, model_id, attempt + 1, int(wait), e.retry_after or 0,
                    )
                    record_attempt(pname, model_id, "rate_limit", 0, str(e))
                    await asyncio.sleep(wait)
                    attempt += 1

                except AuthError as e:
                    last_err = str(e)
                    logger.error("Auto: %s / %s auth error (no retry): %s", pname, model_id, e)
                    record_attempt(pname, model_id, "auth_error", 0, str(e))
                    break

                except ProviderError as e:
                    last_err = str(e)
                    logger.warning(
                        "Auto: %s / %s provider error (attempt %d): %s",
                        pname, model_id, attempt + 1, e,
                    )
                    record_attempt(pname, model_id, "error", 0, str(e))
                    wait = _compute_wait(attempt)
                    await asyncio.sleep(wait)
                    attempt += 1

                except Exception as e:
                    last_err = str(e)
                    logger.error(
                        "Auto: %s / %s unexpected error (attempt %d): %s",
                        pname, model_id, attempt + 1, e,
                    )
                    record_attempt(pname, model_id, "error", 0, str(e))
                    wait = _compute_wait(attempt)
                    await asyncio.sleep(wait)
                    attempt += 1

        return None, last_err

    async def _auto_try_provider_stream(
        self, pname: str, prov: BaseProvider, messages: list, kwargs: dict,
    ) -> tuple[AsyncIterator[bytes] | None, str | None]:
        if prov.circuit_open:
            logger.info("Auto stream: skipping %s (circuit breaker open)", pname)
            return None, f"circuit breaker open for {pname}"

        models = self._provider_models.get(pname, set())
        if not models:
            try:
                fetched = await prov.fetch_models(self._http)
                models = {m["id"] for m in fetched if m.get("id")}
            except Exception:
                return None, f"could not fetch models from {pname}"

        model_list = sorted([m for m in models if m])
        if not model_list:
            return None, f"no models available on {pname}"

        last_err: str | None = None
        for model_id in model_list:
            attempt = 0
            while attempt < MAX_RETRY_PER_MODEL:
                if prov.circuit_open:
                    return None, f"circuit breaker opened for {pname}"

                try:
                    logger.info(
                        "Auto stream: %s / %s (attempt %d/%d)",
                        pname, model_id, attempt + 1, MAX_RETRY_PER_MODEL,
                    )
                    async with prov._semaphore:
                        stream_iter = prov.stream(self._http, model_id, messages, **kwargs)
                    first_chunk: bytes | None = None
                    try:
                        first_chunk = await stream_iter.__anext__()
                    except StopAsyncIteration:
                        break
                    except RateLimitError as e:
                        wait = _compute_wait(attempt, e.retry_after)
                        logger.warning(
                            "Auto stream: %s / %s rate limited (attempt %d) — waiting %ds",
                            pname, model_id, attempt + 1, int(wait),
                        )
                        record_attempt(pname, model_id, "rate_limit", 0, str(e))
                        await asyncio.sleep(wait)
                        attempt += 1
                        continue
                    except (ProviderError, Exception) as e:
                        last_err = str(e)
                        record_attempt(pname, model_id, "error", 0, str(e))
                        wait = _compute_wait(attempt)
                        await asyncio.sleep(wait)
                        attempt += 1
                        continue

                    async def gen(fc: bytes = first_chunk, si=stream_iter, pn=pname, mi=model_id):
                        _auto_prefix = (f"data: {json.dumps({'auto_routed': True, 'provider': pn, 'model': mi})}\n\n").encode()
                        yield _auto_prefix
                        yield fc
                        async for chunk in si:
                            yield chunk

                    return gen(), None

                except RateLimitError as e:
                    wait = _compute_wait(attempt, e.retry_after)
                    logger.warning(
                        "Auto stream: %s / %s rate limited (attempt %d) — waiting %ds",
                        pname, model_id, attempt + 1, int(wait),
                    )
                    record_attempt(pname, model_id, "rate_limit", 0, str(e))
                    await asyncio.sleep(wait)
                    attempt += 1

                except AuthError as e:
                    last_err = str(e)
                    logger.error("Auto stream: %s / %s auth error (no retry): %s", pname, model_id, e)
                    record_attempt(pname, model_id, "auth_error", 0, str(e))
                    break

                except Exception as e:
                    last_err = str(e)
                    logger.error(
                        "Auto stream: %s / %s unexpected error (attempt %d): %s",
                        pname, model_id, attempt + 1, e,
                    )
                    record_attempt(pname, model_id, "error", 0, str(e))
                    wait = _compute_wait(attempt)
                    await asyncio.sleep(wait)
                    attempt += 1

        return None, last_err

    async def route_auto(
        self,
        messages: list,
        **kwargs,
    ) -> dict:
        if not self.providers:
            raise ProviderError("No providers configured")

        trace = current_trace()
        await self.fetch_all_models(force=True)

        ordered = [
            p for p in self.priority
            if p in self.providers and self.providers[p].is_configured
        ]
        if not ordered:
            raise ProviderError("No configured providers available for auto routing")

        last_err: str | None = None
        for pname in ordered:
            prov = self.providers[pname]
            if not prov.is_available:
                reason = "rate limited" if prov.is_rate_limited else "circuit breaker open" if prov.circuit_open else "unavailable"
                logger.info("Auto: skipping %s (%s)", pname, reason)
                continue
            result, err = await self._auto_try_provider(pname, prov, messages, kwargs)
            if result is not None:
                logger.info(
                    "Auto routing succeeded: provider=%s model=%s",
                    result.get("_auto_provider"), result.get("_auto_model"),
                )
                if trace:
                    trace.final_provider = result.get("_auto_provider")
                    trace.final_model = result.get("_auto_model")
                return result
            if err:
                last_err = err
            logger.warning("Auto: provider %s exhausted, moving to next", pname)

        raise ProviderError(
            f"All providers exhausted in auto routing. Last error: {last_err}"
        )

    async def route_auto_stream(
        self,
        messages: list,
        **kwargs,
    ) -> AsyncIterator[bytes]:
        if not self.providers:
            raise ProviderError("No providers configured")

        await self.fetch_all_models(force=True)

        ordered = [
            p for p in self.priority
            if p in self.providers and self.providers[p].is_configured
        ]
        if not ordered:
            raise ProviderError("No configured providers available for auto routing")

        last_err: str | None = None
        for pname in ordered:
            prov = self.providers[pname]
            if not prov.is_available:
                logger.info("Auto stream: skipping %s", pname)
                continue
            gen, err = await self._auto_try_provider_stream(pname, prov, messages, kwargs)
            if gen is not None:
                async for chunk in gen:
                    yield chunk
                return
            if err:
                last_err = err
            logger.warning("Auto stream: provider %s exhausted, moving to next", pname)

        raise ProviderError(
            f"All providers exhausted in auto stream routing. Last error: {last_err}"
        )

    def stats(self) -> dict[str, dict]:
        return {
            name: prov.health_status()
            for name, prov in self.providers.items()
            if prov.is_configured
        }

    async def deep_health(self) -> dict[str, Any]:
        results = {}
        for name, prov in self.providers.items():
            if not prov.is_configured:
                continue
            try:
                models = await asyncio.wait_for(
                    prov.fetch_models(self._http), timeout=10
                )
                results[name] = {
                    "status": "ok",
                    "models": len(models),
                    "circuit": prov.circuit_breaker.state.name,
                    "rate_limited": prov.is_rate_limited,
                }
            except RateLimitError:
                results[name] = {"status": "rate_limited", "circuit": prov.circuit_breaker.state.name}
            except Exception as e:
                results[name] = {"status": "error", "error": str(e), "circuit": prov.circuit_breaker.state.name}
        return results

    async def close(self):
        await self._http.aclose()
