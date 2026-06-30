# Unified Router v2.0.0

**One endpoint to rule them all.** Production-grade LLM router across **44 free providers** with circuit breakers, real retry-after handling, request queues, input validation, and observability.

```bash
pip install git+https://github.com/MrNova420/unified-router.git
unified-router init
unified-router start
```

## What it does

- **Production-grade circuit breaker** per provider — stops calling dead APIs before they hurt you
- **Real retry-after handling** — when rate limited, waits the ACTUAL time the provider says (not a guess)
- **Single OpenAI-compatible endpoint** (`/v1/chat/completions`)
- **Auto-discovers** all models from every provider you configure
- **Smart provider fallback** — if one provider rate-limits or errors, automatically tries the next
- **Smart model fallback** — if ALL providers fail for a model, auto-finds similar models and retries across all providers
- **Full auto model routing** — omit `model` or send `"auto"` — router picks the best available model automatically, with 6-retry backoff per model
- **Structured observability** — request tracing with UUIDs, per-request latency tracking, structured logging
- **Input validation** — Pydantic validates temperature, max_tokens, messages, etc.
- **Streaming support** — real-time SSE passthrough with fallback on stream errors
- **Web settings panel** — configure providers and server from your browser
- **Hot reload** — config changes detected and applied without restarting
- **Works with OpenCode, Cursor, any OpenAI-compatible client**

## Install

```bash
# Standard install
pip install git+https://github.com/MrNova420/unified-router.git

# For Ubuntu/Debian users (if you get 'externally-managed-environment' error):
pip install git+https://github.com/MrNova420/unified-router.git --break-system-packages
```

Or clone and install locally:

```bash
git clone https://github.com/MrNova420/unified-router.git
cd unified-router
pip install -e .
```

## Quick Start

```bash
unified-router init        # Interactive setup wizard
unified-router start       # Start the server at http://localhost:3333
```

That's it. Open `http://localhost:3333/admin` for the dashboard or `http://localhost:3333/settings` to configure providers from your browser.

## Use with OpenCode

Add to your `~/.config/opencode/opencode.jsonc`:

```jsonc
{
  "$schema": "https://opencode.ai/config.json",
  "provider": {
    "unified-router": {
      "npm": "@ai-sdk/openai-compatible",
      "name": "Unified Router",
      "options": {
        "baseURL": "http://localhost:3333/v1"
      }
    }
  }
}
```

Now in OpenCode, run `/models` and pick any model from any provider. The router handles the rest.

## How Routing Works

### Mode 1: Specific Model Request

```
Request: model="qwen3-coder"
  → Try OpenRouter (has it?) → Yes → Send → 200? → Return ✓
  → OpenRouter 429? → Skip → Try Groq (has it?) → Yes → Send → 200? → Return ✓
  → Groq down? → Skip → Try NVIDIA (has it?) → Send → 200? → Return ✓
  → All providers failed for "qwen3-coder"?
      → Auto-find similar models (token-overlap matching)
      → Try "qwen3-coder-free" across all providers → Return ✓
      → Try "qwen2.5-coder-32b" across all providers → Return ✓
  → All providers + all similar models failed → Return error
```

### Mode 2: Auto Model Routing (model="auto" or omitted)

```
Request: model="auto" (or model field omitted)
  → Provider 1 (OpenRouter) in priority order:
      → Try model_1 → retry 6× (using Retry-After header if present) → all fail?
      → Try model_2 → retry 6× → all fail?
      → ... try all models ... → ALL models on OpenRouter failed
  → Provider 2 (NVIDIA):
      → Try model_1 → retry 6× → success? → Return ✓
  → All providers exhausted → Return error
```

The auto router stays on each provider until **every** model has been exhausted, then moves to the next provider. When a provider returns a `Retry-After` header, the router **legitimately waits** that exact amount of time (up to 5 minutes). If the header isn't present, it uses a fallback schedule: 5s → 10s → 20s → 40s → 60s → 120s.

The router:
1. Checks which providers have the requested model (fetched and cached)
2. Tries providers in priority order
3. On 429/5xx/connection error → automatically tries next provider
4. If **all providers** fail for the requested model → searches for similar models and retries across all providers
5. Returns the first successful response, or error if everything fails

When `model` is `"auto"` or omitted, the router:
1. Walks through providers in priority order
2. On each provider, tries every model it offers (in API order)
3. Each model gets 6 retries with smart backoff (uses Retry-After if provided, else fallback schedule)
4. Stays on a provider until ALL its models fail, then moves to the next
5. Returns the first successful response with `_auto_provider` and `_auto_model` metadata

## All 44 Supported Providers

### [Easy] No phone, no credit card required

| # | Provider | Free Tier | Env Variable |
|---|---|----------|-----------|-------------|
| 1 | OpenRouter | 20 req/min, 50 req/day free models | `OPENROUTER_API_KEY` |
| 2 | Groq | 1000-14000 req/day per model | `GROQ_API_KEY` |
| 3 | Cerebras | 30 req/min, 900 req/hr | `CEREBRAS_API_KEY` |
| 4 | Cohere | 20 req/min, 1000 req/mo | `COHERE_API_KEY` |
| 5 | HuggingFace Inference | $0.10/mo credits | `HF_TOKEN` |
| 6 | **OpenCode Zen** | Free models available | `OPENCODE_API_KEY` |
| 7 | Together AI | $1 trial credits | `TOGETHER_API_KEY` |
| 8 | Fireworks AI | $1 free credits | `FIREWORKS_API_KEY` |
| 9 | GitHub Models | Free with Copilot | `GITHUB_TOKEN` |
| 10 | 302.AI | Free tier available | `AI302_API_KEY` |
| 11 | Cortecs AI | Free tier available | `CORTECS_API_KEY` |
| 12 | FrogBot | Free tier available | `FROGBOT_API_KEY` |
| 13 | Venice AI | Free tier available | `VENICE_API_KEY` |
| 14 | IO.NET | Free tier available (17 models) | `IO_NET_API_KEY` |
| 15 | GMI Cloud | Free tier available | `GMI_CLOUD_API_KEY` |
| 16 | MiniMax AI | Free tier available | `MINIMAX_API_KEY` |
| 17 | Moonshot AI | Free tier available (Kimi K2) | `MOONSHOT_API_KEY` |

### [Phone] Phone verification required

| # | Provider | Free Tier | Env Variable |
|---|---|----------|-----------|-------------|
| 1 | NVIDIA NIM | 40 req/min | `NVIDIA_API_KEY` |
| 2 | Mistral La Plateforme | 1 req/s, 1B tokens/mo | `MISTRAL_API_KEY` |
| 3 | Mistral Codestral | 30 req/min, 2000 req/day | `CODESTRAL_API_KEY` |
| 4 | NLP Cloud | $15 free credits | `NLP_CLOUD_API_KEY` |

### [Credits] No free tier

| # | Provider | Free Tier | Env Variable |
|---|---|----------|-----------|-------------|
| 1 | **xAI** | $25 credits + $150/mo data sharing | `XAI_API_KEY` |
| 2 | Nebius AI | $1 free credits | `NEBIUS_API_KEY` |
| 3 | Novita AI | $0.50 free credits | `NOVITA_API_KEY` |
| 4 | Hyperbolic | $1 free credits | `HYPERBOLIC_API_KEY` |
| 5 | SambaNova Cloud | $5 free credits (3mo) | `SAMBANOVA_API_KEY` |
| 6 | Scaleway AI | 1M free tokens | `SCALEWAY_API_KEY` |
| 7 | Baseten | $30 free credits | `BASETEN_API_KEY` |
| 8 | AI21 Labs | $10 free credits (3mo) | `AI21_API_KEY` |
| 9 | Upstage AI | $10 free credits (3mo) | `UPSTAGE_API_KEY` |
| 10 | Deep Infra | Pay-as-you-go (cheap) | `DEEPINFRA_API_KEY` |
| 11 | DeepSeek | Very cheap paid | `DEEPSEEK_API_KEY` |
| 12 | Alibaba Cloud Model Studio | 1M free tokens/model | `ALIBABA_API_KEY` |
| 13 | Inference.net | $1 free credits | `INFERENCE_NET_API_KEY` |

### [Paid] No free tier

| # | Provider | Env Variable |
|---|---|----------|-------------|
| 1 | DigitalOcean GPU | `DIGITALOCEAN_API_KEY` |
| 2 | OVHcloud AI Endpoints | `OVHCLOUD_API_KEY` |
| 3 | STACKIT AI | `STACKIT_API_KEY` |
| 4 | SAP AI Core | `SAP_AI_API_KEY` |
| 5 | Snowflake Cortex AI | `SNOWFLAKE_API_KEY` |
| 6 | Ollama Cloud | `OLLAMA_CLOUD_API_KEY` |
| 7 | Vercel AI Gateway | `VERCEL_AI_API_KEY` |
| 8 | Modal | `MODAL_API_KEY` |

### Custom API Providers (4)

| # | Provider | Free Tier | Env Variable |
|---|---|----------|-----------|-------------|
| 1 | Google Gemini | 20-1500 req/day per model | `GEMINI_API_KEY` |
| 2 | Cloudflare Workers AI | 10k neurons/day | `CLOUDFLARE_API_TOKEN` + `CLOUDFLARE_ACCOUNT_ID` |
| 3 | Cohere | 20 req/min, 1000 req/mo | `COHERE_API_KEY` |
| 4 | HuggingFace Inference | $0.10/mo credits | `HF_TOKEN` |

## CLI Commands

| Command | Description |
|---------|-------------|
| `unified-router init` | Interactive setup wizard (auto-detects env keys) |
| `unified-router init --auto` | Non-interactive — use env-detected keys only |
| `unified-router init --guide` | Walk through signing up for top providers |
| `unified-router start` | Start the server |
| `unified-router version` | Show version |
| `unified-router models` | List all available models |
| `unified-router status` | Show provider configuration (keys masked) |
| `unified-router providers` | List all 44 providers with type badges |
| `unified-router health` | Ping all providers, check connectivity |
| `unified-router config` | Print current config |
| `unified-router guide` | Walk through signing up for top providers |
| `unified-router dashboard` | Live usage stats (terminal) |
| `unified-router dashboard --once` | One-shot stats snapshot |
| `unified-router add-key <provider> <key>` | Add an API key |
| `unified-router remove-key <provider>` | Remove an API key |
| `unified-router install-service` | Install as system service (Linux/macOS/Windows) |

## Web UI

The server includes two web pages:

### `/admin` — Live Dashboard
- Provider stats (requests, errors, tokens, latency)
- Rate-limit and circuit breaker status per provider
- Cache hit/miss stats
- Model list (first 100)
- Auto-refreshes every 3 seconds
- One-click config reload

### `/settings` — Setup Panel
- Edit all provider API keys (password-masked inputs)
- Edit server host, port, log level
- See which providers are configured (✅/❌)
- Save keys and server config directly to `config.yml`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/v1/models` | List all models across all providers |
| `POST` | `/v1/chat/completions` | Chat completion (streaming + non-streaming) |
| `GET` | `/v1/stats` | Provider stats + queue stats JSON |
| `GET` | `/health` | Deep health check (per-provider ping) |
| `POST` | `/reload` | Hot reload config without restart |
| `GET` | `/admin` | Live dashboard (HTML) |
| `GET` | `/settings` | Setup panel (HTML) |
| `GET` | `/settings/api` | Current config JSON (for settings panel) |
| `POST` | `/settings/server` | Save server settings to config.yml |
| `POST` | `/settings/keys` | Save provider API keys to config.yml |
| `GET` | `/docs` | Swagger API docs |

## Configuration

Config file: `~/.config/unified-router/config.yml` — created by `unified-router init`.

```yaml
server:
  host: "127.0.0.1"
  port: 3333
  log_level: "info"

strategy: "priority"          # priority, round_robin, least_latency, weighted

priority:
  - openrouter
  - groq
  - gemini
  # ... all 44 providers in default order

# Force a model to always use one provider
model_pinning:
  gpt-4o-mini: openrouter
  llama-3.3-70b: groq

# Cache identical requests
cache:
  enabled: true
  ttl: 3600

# Weighted strategy only
load_balance_weights:
  openrouter: 5
  groq: 3

providers:
  openrouter:
    base_url: "https://openrouter.ai/api/v1"
    env_key: "OPENROUTER_API_KEY"
    api_key: "${OPENROUTER_API_KEY}"
  groq:
    base_url: "https://api.groq.com/openai/v1"
    env_key: "GROQ_API_KEY"
    api_key: "${GROQ_API_KEY}"
```

Values like `${VAR_NAME}` are resolved from environment variables at startup.

## Environment Variables

All 44 provider keys are auto-detected from environment variables. Set what you have:

```bash
export OPENROUTER_API_KEY="sk-or-..."
export GROQ_API_KEY="gsk_..."
export GEMINI_API_KEY="AIza..."
export NVIDIA_API_KEY="nvapi-..."
export XAI_API_KEY="xai_..."
export CEREBRAS_API_KEY="cerebras_..."
# ... etc

unified-router start
```

### `.env` file support

Instead of exporting vars, create `~/.config/unified-router/.env`:

```
OPENROUTER_API_KEY=sk-or-...
GROQ_API_KEY=gsk_...
GEMINI_API_KEY=AIza...
```

The router loads this file automatically on startup.

## Features

### Automatic Provider Fallback
If a provider rate-limits (429), errors (5xx), or times out, the router automatically tries the next provider in priority order that has the requested model.

### Full Auto Model Routing
Send `model: "auto"` (or omit the `model` field entirely) and the router picks the best available model automatically:
- Walks providers in priority order
- On each provider, tries every model in API order
- Each model gets 6 retries with smart backoff (uses provider's `Retry-After` if available, else 5s → 10s → 20s → 40s → 60s → 120s)
- Only moves to next provider after ALL models on current provider fail
- Responses include `_auto_provider` and `_auto_model` fields
- Streaming responses include an `auto_routed` SSE prefix event

```bash
# Auto routing — no model selection needed
curl -X POST http://localhost:3333/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

### Automatic Model Fallback
If **all providers** fail for the requested model, the router searches for **similar models** using token-overlap matching and tries those across all providers. The response includes `_fallback_model` and `_original_model` fields when a substitute was used.

### Streaming Support
Pass `"stream": true` in your `/v1/chat/completions` request. The router streams Server-Sent Events chunks in real-time. If the streaming provider fails (detected on first chunk), the router falls back to the next provider automatically.

### Circuit Breaker
Each provider gets an independent circuit breaker:
- After 5 consecutive failures, the circuit **opens** and stops sending requests
- After 60 seconds, it enters **half-open** mode and tests with limited traffic
- On success, the circuit **closes** and normal operation resumes
- Prevents overwhelming dead APIs, reducing waste of free-tier quota

### Concurrency Control
Each provider has a semaphore limiting max concurrent requests (default 10). Prevents thundering-herd against rate-limited free APIs.

### Request Queue with Backpressure
When all providers are rate-limited or circuits are open, requests are queued instead of failing immediately. Configurable max queue size (default 100). If queue is full, returns a clear error telling the client to retry later.

### Load Balancing Strategies
Set `strategy` in config.yml:
```yaml
strategy: priority       # default — try providers top-to-bottom
strategy: round_robin    # rotate through providers per request
strategy: least_latency  # use provider with lowest EMA latency
strategy: weighted       # use load_balance_weights
```

### Per-Model Provider Pinning
Force a specific model to always use a specific provider:
```yaml
model_pinning:
  gpt-4o: openrouter
  llama-3.3-70b: groq
```

### Request/Response Caching
```yaml
cache:
  enabled: true
  ttl: 3600  # seconds
```
Identical requests (same model + messages + params) return cached results without hitting the provider, saving your free-tier quota.

### Usage Tracking & Dashboard
Every provider tracks requests, errors, tokens, and latency (exponential moving average). View live:
- **Web UI:** Open `http://localhost:3333/admin` in your browser
- **JSON API:** `GET /v1/stats`
- **Terminal:** `unified-router dashboard` (live-refreshing) or `unified-router dashboard --once`

### Plugin System
Drop a `.py` file in `~/.config/unified-router/plugins/` containing a `BaseProvider` subclass. It's auto-discovered and added to your providers. Configure it under a `plugins:` section in config.yml:
```yaml
plugins:
  my_custom_provider:
    api_key: "..."
    base_url: "https://my-internal-llm/v1"
```

### Hot Reload
Edit `~/.config/unified-router/config.yml` and changes are detected automatically within 5 seconds. Or POST to `/reload` to trigger manually. No restart needed.

## Architecture

```
┌─────────────┐     ┌─────────────────────────────────────┐     ┌──────────────────┐
│  OpenCode   │────▶│  Unified Router (localhost:3333)    │────▶│  OpenRouter      │
│  Any Client │     │                                     │     │  Groq            │
└─────────────┘     │  /v1/chat/completions               │     │  Cerebras        │
                    │  /v1/models                         │     │  NVIDIA          │
                    │  /admin  (dashboard)                │     │  DeepSeek        │
                    │  /settings  (setup panel)           │     │  Gemini          │
                    │  /health                            │     │  xAI             │
                    │  /reload                            │     │  Cohere          │
                    │                                     │     │  Cloudflare      │
                    │  Router → Provider A → 429?         │     │  +36 more        │
                    │         → Provider B → 200! ✓       │     │                  │
                    │         → All fail? → Model fallback │     │                  │
                    │                                     │     │                  │
                    │  44 providers in registry.yaml       │     │                  │
                    │  Circuit breakers + Queue + CB +    │     │                  │
                    │  Real retry-after + Observability   │     │                  │
                    └─────────────────────────────────────┘     └──────────────────┘
```

Providers are defined as pure data in `src/unified_router/registry.yaml`. To add a new OpenAI-compatible provider, add 5-8 lines of YAML — no code changes needed.

## Docker

```bash
docker build -t unified-router .
docker run -d \
  -p 3333:3333 \
  -v ~/.config/unified-router:/root/.config/unified-router \
  unified-router
```

The Dockerfile includes a health check against `/health`.

## Development

```bash
git clone https://github.com/MrNova420/unified-router.git
cd unified-router
pip install -e .
unified-router init
unified-router start
```

### Testing

```bash
pip install pytest pytest-asyncio
PYTHONPATH=src pytest tests/ -v
```

## Roadmap

- [x] Auto-discover models from each provider's /v1/models
- [x] Smart provider fallback (429/error → next provider)
- [x] Smart model fallback (all providers fail → find similar models)
- [x] Full auto model routing (model="auto" → try all models on all providers)
- [x] Streaming support (SSE passthrough + fallback on error)
- [x] Load balancing (priority, round-robin, least-latency, weighted)
- [x] Per-model provider pinning
- [x] Request/response caching with TTL
- [x] Usage tracking + dashboard (terminal + web)
- [x] Plugin system for custom providers
- [x] Web admin dashboard at /admin
- [x] Web settings panel at /settings
- [x] Health endpoint + CORS middleware
- [x] .env file support
- [x] Circuit breaker per provider
- [x] Real retry-after header handling
- [x] Concurrency control (semaphores)
- [x] Request queue with backpressure
- [x] Structured observability (tracing, logging)
- [x] Input validation (Pydantic)
- [x] Hot reload
- [ ] Prompt template optimization per provider
- [ ] PyPI release

## License

MIT
