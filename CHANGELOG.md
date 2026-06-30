# Changelog

# Changelog

## v2.0.0

- **Production-grade reliability**: Circuit breaker per provider (no more hammering dead APIs)
- **Realistic retry with retry-after**: When rate limited, uses the ACTUAL `Retry-After` header from providers, not hardcoded numbers. Waits as long as the provider says.
- **Concurrency control**: Per-provider semaphore limits prevent overwhelming any single provider
- **Request queue with backpressure**: Gracefully handles provider outages by queuing instead of failing immediately. Configurable max queue size.
- **Structured observability**: Request tracing with UUIDs, structured logging, per-request latency tracking across all provider attempts
- **Input validation**: Pydantic validators on `temperature`, `max_tokens`, `messages` (not empty)
- **Consistent error handling**: Standardized error responses (401/429/503/500), centralized exception handlers per error type
- **Deep health checks**: `/health` now pings every provider and reports real status per provider (not just "ok")
- **Hot reload**: Config file changes are detected and reloaded without restart. Also `/reload` endpoint for manual trigger
- **Security**: API keys masked in `/settings/api`, `AuthError` for 401s, per-provider health status endpoint
- **Admin dashboard**: Now shows circuit breaker state per provider, visual indicators for rate limited vs circuit open vs OK
- **Tests**: 14 tests covering circuit breaker, provider initialization, error handling, health status

## v1.1.0

- **Full auto model routing**: send `model: "auto"` or omit `model` entirely — router picks the best available model automatically
- Provider-priority-first traversal: stays on each provider until ALL its models fail, then moves to next
- 6 retries per model with realistic exponential backoff (2s, 5s, 10s, 20s, 40s, 60s)
- Works for both streaming and non-streaming requests
- Auto-routed responses include `_auto_provider` and `_auto_model` metadata
- Streaming auto responses include an `auto_routed` SSE event prefix with provider/model info
- `model` field in ChatRequest is now optional (defaults to `"auto"`)

## v1.0.0

- Fixed streaming fallback bug: errors now detected before yielding chunks
- Added `/health` endpoint for monitoring
- Added CORS middleware for cross-origin requests
- Added graceful shutdown with cleanup
- Added CLI commands: `version`, `models`, `add-key`, `remove-key`
- Added config validation on startup with helpful error messages
- Added `.env` file support (`~/.config/unified-router/.env`)
- Added `MANIFEST.in` for PyPI (includes registry.yaml)
- Added MIT LICENSE
- Added `__version__` to package

## v0.4.0

- Streaming support (SSE passthrough)
- Load balancing strategies (priority/round_robin/least_latency/weighted)
- Automatic model fallback (token-overlap similarity matching)
- Per-model provider pinning
- Request/response caching with TTL
- Usage tracking (requests/errors/tokens/latency EMA)
- Dashboard CLI command
- Plugin system (`~/.config/unified-router/plugins/*.py`)
- Web admin UI at `/admin`
- `/v1/stats` JSON endpoint

## v0.3.0

- OpenCode Zen + xAI providers (44 total)
- Provider type badges ([Easy]/[Phone]/[Credits]/[Paid])
- Grouped provider display
- Browser-open shortcut in init wizard
- `--guide` mode
- Post-init health check

## v0.2.0

- YAML registry architecture (registry.yaml)
- 42 providers
- Cohere + HuggingFace custom adapters
- Rewritten CLI/config

## v0.1.0

- Initial release with 11 providers
- Hardcoded provider registry
