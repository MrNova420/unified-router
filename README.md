# Unified Router

**One endpoint to rule them all.** Route LLM requests across **44 free providers** worldwide with automatic fallback.

```
pip install unified-router
unified-router init
unified-router start
```

## What it does

- **Single OpenAI-compatible endpoint** (`/v1/chat/completions`)
- **Auto-discovers** all models from every provider you configure
- **Smart fallback** — if one provider rate-limits or errors, seamlessly tries the next
- **Works with OpenCode, Cursor, any OpenAI-compatible client**

## All 42 Supported Providers

### OpenAI-Compatible (40 providers)

| # | Provider | Free Tier | Env Variable |
|---|----------|-----------|-------------|
| 1 | OpenRouter | 20 req/min, 50 req/day free models | `OPENROUTER_API_KEY` |
| 2 | Groq | 1000-14000 req/day per model | `GROQ_API_KEY` |
| 3 | **OpenCode Zen** | Free models: Big Pickle, DeepSeek V4 Flash Free | `OPENCODE_API_KEY` |
| 4 | Cerebras | 30 req/min, 900 req/hr | `CEREBRAS_API_KEY` |
| 5 | NVIDIA NIM | 40 req/min (phone verify) | `NVIDIA_API_KEY` |
| 6 | Mistral La Plateforme | 1 req/s, 1B tokens/mo | `MISTRAL_API_KEY` |
| 7 | Mistral Codestral | 30 req/min, 2000 req/day | `CODESTRAL_API_KEY` |
| 8 | DeepSeek | Paid (very cheap) | `DEEPSEEK_API_KEY` |
| 9 | **xAI Grok** | $25 credits + $150/mo data sharing | `XAI_API_KEY` |
| 10 | Together AI | $1 trial credits | `TOGETHER_API_KEY` |
| 11 | Fireworks AI | $1 free credits | `FIREWORKS_API_KEY` |
| 12 | Deep Infra | Pay-as-you-go (cheap) | `DEEPINFRA_API_KEY` |
| 13 | GitHub Models | Free with Copilot | `GITHUB_TOKEN` |
| 14 | 302.AI | Free tier available | `AI302_API_KEY` |
| 15 | Nebius AI | $1 free credits | `NEBIUS_API_KEY` |
| 16 | Novita AI | $0.50 free credits | `NOVITA_API_KEY` |
| 17 | Hyperbolic | $1 free credits | `HYPERBOLIC_API_KEY` |
| 18 | SambaNova Cloud | $5 free credits (3mo) | `SAMBANOVA_API_KEY` |
| 19 | Scaleway AI | 1M free tokens | `SCALEWAY_API_KEY` |
| 20 | Venice AI | Free tier available | `VENICE_API_KEY` |
| 21 | Baseten | $30 free credits | `BASETEN_API_KEY` |
| 22 | GMI Cloud | Free tier available | `GMI_CLOUD_API_KEY` |
| 23 | IO.NET | Free tier available (17 models) | `IO_NET_API_KEY` |
| 24 | Cortecs AI | Free tier available | `CORTECS_API_KEY` |
| 25 | FrogBot | Free tier available | `FROGBOT_API_KEY` |
| 26 | MiniMax AI | Free tier available | `MINIMAX_API_KEY` |
| 27 | Moonshot AI | Free tier available (Kimi K2) | `MOONSHOT_API_KEY` |
| 28 | AI21 Labs | $10 free credits (3mo) | `AI21_API_KEY` |
| 29 | Upstage AI | $10 free credits (3mo) | `UPSTAGE_API_KEY` |
| 30 | NLP Cloud | $15 free credits (phone verify) | `NLP_CLOUD_API_KEY` |
| 31 | Alibaba Cloud Model Studio | 1M free tokens/model | `ALIBABA_API_KEY` |
| 32 | DigitalOcean GPU | Free tier available | `DIGITALOCEAN_API_KEY` |
| 33 | OVHcloud AI Endpoints | Free tier available | `OVHCLOUD_API_KEY` |
| 34 | STACKIT AI | Free tier available | `STACKIT_API_KEY` |
| 35 | SAP AI Core | Free tier available | `SAP_AI_API_KEY` |
| 36 | Snowflake Cortex AI | Free tier available | `SNOWFLAKE_API_KEY` |
| 37 | Ollama Cloud | Free tier available | `OLLAMA_CLOUD_API_KEY` |
| 38 | Vercel AI Gateway | $5/mo free tier | `VERCEL_AI_API_KEY` |
| 39 | Modal | $5/mo free credits | `MODAL_API_KEY` |
| 40 | Inference.net | $1 free credits | `INFERENCE_NET_API_KEY` |

### Custom API (4 providers)

| # | Provider | Free Tier | Env Variable |
|---|----------|-----------|-------------|
| 41 | Google Gemini | 20-1500 req/day per model | `GEMINI_API_KEY` |
| 42 | Cloudflare Workers AI | 10k neurons/day | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` |
| 43 | Cohere | 20 req/min, 1000 req/mo | `COHERE_API_KEY` |
| 44 | HuggingFace Inference | $0.10/mo credits | `HF_TOKEN` |

## Quick Start

```bash
# Install
pip install unified-router

# Interactive setup — walks through each provider
unified-router init

# Start the server
unified-router start
```

That's it. Server runs at `http://localhost:3333`.

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

Now in OpenCode, run `/models` and pick any model from any provider. The router will automatically try providers in order and fall back if one fails.

## CLI Commands

| Command | Description |
|---------|-------------|
| `unified-router init` | Interactive setup wizard |
| `unified-router start` | Start the server |
| `unified-router status` | Show provider configuration |
| `unified-router providers` | List all providers |
| `unified-router health` | Ping all providers, check connectivity |
| `unified-router config` | Print current config |
| `unified-router guide` | Walk through signing up for top providers |
| `unified-router dashboard` | Live usage stats (terminal) |
| `unified-router install-service` | Install as system service |

## Docker

```bash
docker run -d \
  -p 3333:3333 \
  -v ~/.config/unified-router:/root/.config/unified-router \
  ghcr.io/mrnova420/unified-router
```

## Environment Variables

All 42 provider keys are auto-detected from environment variables. Just export what you have:

```bash
# OpenAI compatible providers
export OPENROUTER_API_KEY="sk-or-..."
export GROQ_API_KEY="gsk_..."
export CEREBRAS_API_KEY="cerebras_..."
export NVIDIA_API_KEY="nvapi-..."
export MISTRAL_API_KEY="..."
export CODESTRAL_API_KEY="..."
export DEEPSEEK_API_KEY="sk-..."
export TOGETHER_API_KEY="..."
export FIREWORKS_API_KEY="..."
export DEEPINFRA_API_KEY="..."
export GITHUB_TOKEN="ghp_..."
export OPENCODE_API_KEY="oc_..."
export XAI_API_KEY="xai_..."
export AI302_API_KEY="..."
export NEBIUS_API_KEY="..."
export NOVITA_API_KEY="..."
export HYPERBOLIC_API_KEY="..."
export SAMBANOVA_API_KEY="..."
export SCALEWAY_API_KEY="..."
export VENICE_API_KEY="..."
export BASETEN_API_KEY="..."
export GMI_CLOUD_API_KEY="..."
export IO_NET_API_KEY="..."
export CORTECS_API_KEY="..."
export FROGBOT_API_KEY="..."
export MINIMAX_API_KEY="..."
export MOONSHOT_API_KEY="..."
export AI21_API_KEY="..."
export UPSTAGE_API_KEY="..."
export NLP_CLOUD_API_KEY="..."
export ALIBABA_API_KEY="..."
export DIGITALOCEAN_API_KEY="..."
export OVHCLOUD_API_KEY="..."
export STACKIT_API_KEY="..."
export SAP_AI_API_KEY="..."
export SNOWFLAKE_API_KEY="..."
export OLLAMA_CLOUD_API_KEY="..."
export VERCEL_AI_API_KEY="..."
export MODAL_API_KEY="..."
export INFERENCE_NET_API_KEY="..."

# Custom API providers
export GEMINI_API_KEY="AIza..."
export CLOUDFLARE_API_TOKEN="..."
export CLOUDFLARE_ACCOUNT_ID="..."
export COHERE_API_KEY="..."
export HF_TOKEN="hf_..."

unified-router start
```

## How Routing Works

```
Request: model="qwen3-coder"
  → Try OpenRouter (has it?) → Yes → Send → 200? → Return
  → OpenRouter 429? → Skip → Try Groq → Send → 200? → Return
  → Groq down? → Skip → Try Cloudflare → Send → 200? → Return
  → All failed → Return error
```

The router:
1. Checks each provider's available models (fetched and cached)
2. Tries providers in priority order
3. On 429/503/connection error → automatically tries next
4. Returns the first successful response

## Architecture

```
┌─────────────┐     ┌─────────────────────────────────────┐     ┌──────────────────┐
│  OpenCode   │────▶│  Unified Router (localhost:3333)    │────▶│  OpenRouter      │
│  Any Client │     │                                     │     │  Groq            │
└─────────────┘     │  /v1/chat/completions               │     │  Cerebras        │
                    │  /v1/models                         │     │  NVIDIA          │
                    │                                     │     │  DeepSeek        │
                    │  Router → Provider A → 429?         │     │  Gemini          │
                    │         → Provider B → 200! ✓       │     │  Cohere          │
                    │                                     │     │  Cloudflare      │
                    │  44 providers in registry.yaml       │     │  +38 more        │
                    └─────────────────────────────────────┘     └──────────────────┘
```

Providers are defined as data in `src/unified_router/registry.yaml`. To add a new OpenAI-compatible provider, add 5 lines to that file — no code changes needed.

## Config File

`~/.config/unified-router/config.yml` — created by `unified-router init`.

```yaml
server:
  host: "127.0.0.1"
  port: 3333

priority:
  - openrouter
  - groq
  - cerebras
  # ... all 44 providers

providers:
  openrouter:
    base_url: "https://openrouter.ai/api/v1"
    api_key: "${OPENROUTER_API_KEY}"
```

Values like `${VAR_NAME}` are resolved from environment variables.

## Development

```bash
git clone https://github.com/mrnova420/unified-router
cd unified-router
pip install -e .
unified-router init
unified-router start
```

## Features

### Automatic Fallback (Provider)
If a provider rate-limits (429), errors (5xx), or times out, the router automatically tries the next provider in priority order that has the requested model.

### Automatic Model Fallback
If **all providers** fail for the requested model, the router searches for **similar models** (token-overlap matching) and tries those across all providers. The response includes `_fallback_model` and `_original_model` fields when a substitute was used.

### Streaming Support
Pass `"stream": true` in your `/v1/chat/completions` request. The router streams Server-Sent Events chunks from the provider in real-time. OpenAI-compatible providers stream natively; custom adapters (Gemini, Cohere, Cloudflare) fall back to simulated streaming. If the streaming provider fails mid-stream, the router falls back to the next provider.

### Load Balancing Strategies
Set `strategy` in config.yml:
```yaml
strategy: priority       # default — try providers top-to-bottom
strategy: round_robin    # rotate through providers per request
strategy: least_latency  # use provider with lowest EMA latency
strategy: weighted       # use load_balance_weights (below)
load_balance_weights:
  openrouter: 5
  groq: 3
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

## Roadmap

- [x] Per-model provider pinning
- [x] Load balancing (priority, round-robin, least-latency, weighted)
- [x] Usage dashboard (terminal UI + web admin)
- [x] Request/response caching
- [x] Streaming support
- [x] Plugin system for custom providers
- [x] Web UI for stats at /admin
- [x] Automatic model fallback when all providers fail
- [ ] Prompt template optimization per provider
- [ ] PyPI release
