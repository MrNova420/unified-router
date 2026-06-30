# Unified Router

**One endpoint to rule them all.** Route LLM requests across **42 free providers** worldwide with automatic fallback.

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

### OpenAI-Compatible (38 providers)

| # | Provider | Free Tier | Env Variable |
|---|----------|-----------|-------------|
| 1 | OpenRouter | 20 req/min, 50 req/day free models | `OPENROUTER_API_KEY` |
| 2 | Groq | 1000-14000 req/day per model | `GROQ_API_KEY` |
| 3 | Cerebras | 30 req/min, 900 req/hr | `CEREBRAS_API_KEY` |
| 4 | NVIDIA NIM | 40 req/min (phone verify) | `NVIDIA_API_KEY` |
| 5 | Mistral La Plateforme | 1 req/s, 1B tokens/mo | `MISTRAL_API_KEY` |
| 6 | Mistral Codestral | 30 req/min, 2000 req/day | `CODESTRAL_API_KEY` |
| 7 | DeepSeek | Paid (very cheap) | `DEEPSEEK_API_KEY` |
| 8 | Together AI | $1 trial credits | `TOGETHER_API_KEY` |
| 9 | Fireworks AI | $1 free credits | `FIREWORKS_API_KEY` |
| 10 | Deep Infra | Pay-as-you-go (cheap) | `DEEPINFRA_API_KEY` |
| 11 | GitHub Models | Free with Copilot | `GITHUB_TOKEN` |
| 12 | 302.AI | Free tier available | `AI302_API_KEY` |
| 13 | Nebius AI | $1 free credits | `NEBIUS_API_KEY` |
| 14 | Novita AI | $0.50 free credits | `NOVITA_API_KEY` |
| 15 | Hyperbolic | $1 free credits | `HYPERBOLIC_API_KEY` |
| 16 | SambaNova Cloud | $5 free credits (3mo) | `SAMBANOVA_API_KEY` |
| 17 | Scaleway AI | 1M free tokens | `SCALEWAY_API_KEY` |
| 18 | Venice AI | Free tier available | `VENICE_API_KEY` |
| 19 | Baseten | $30 free credits | `BASETEN_API_KEY` |
| 20 | GMI Cloud | Free tier available | `GMI_CLOUD_API_KEY` |
| 21 | IO.NET | Free tier available (17 models) | `IO_NET_API_KEY` |
| 22 | Cortecs AI | Free tier available | `CORTECS_API_KEY` |
| 23 | FrogBot | Free tier available | `FROGBOT_API_KEY` |
| 24 | MiniMax AI | Free tier available | `MINIMAX_API_KEY` |
| 25 | Moonshot AI | Free tier available (Kimi K2) | `MOONSHOT_API_KEY` |
| 26 | AI21 Labs | $10 free credits (3mo) | `AI21_API_KEY` |
| 27 | Upstage AI | $10 free credits (3mo) | `UPSTAGE_API_KEY` |
| 28 | NLP Cloud | $15 free credits (phone verify) | `NLP_CLOUD_API_KEY` |
| 29 | Alibaba Cloud Model Studio | 1M free tokens/model | `ALIBABA_API_KEY` |
| 30 | DigitalOcean GPU | Free tier available | `DIGITALOCEAN_API_KEY` |
| 31 | OVHcloud AI Endpoints | Free tier available | `OVHCLOUD_API_KEY` |
| 32 | STACKIT AI | Free tier available | `STACKIT_API_KEY` |
| 33 | SAP AI Core | Free tier available | `SAP_AI_API_KEY` |
| 34 | Snowflake Cortex AI | Free tier available | `SNOWFLAKE_API_KEY` |
| 35 | Ollama Cloud | Free tier available | `OLLAMA_CLOUD_API_KEY` |
| 36 | Vercel AI Gateway | $5/mo free tier | `VERCEL_AI_API_KEY` |
| 37 | Modal | $5/mo free credits | `MODAL_API_KEY` |
| 38 | Inference.net | $1 free credits | `INFERENCE_NET_API_KEY` |

### Custom API (4 providers)

| # | Provider | Free Tier | Env Variable |
|---|----------|-----------|-------------|
| 39 | Google Gemini | 20-1500 req/day per model | `GEMINI_API_KEY` |
| 40 | Cloudflare Workers AI | 10k neurons/day | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` |
| 41 | Cohere | 20 req/min, 1000 req/mo | `COHERE_API_KEY` |
| 42 | HuggingFace Inference | $0.10/mo credits | `HF_TOKEN` |

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
                    │  42 providers in registry.yaml       │     │  +36 more        │
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
  # ... all 42 providers

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

## Roadmap

- [ ] Per-model provider pinning (force specific models to specific providers)
- [ ] Load balancing (use multiple providers simultaneously)
- [ ] Usage dashboard (rich terminal UI)
- [ ] Request/response caching
- [ ] Streaming support
- [ ] Prompt template optimization per provider
- [ ] Plugin system for custom providers
- [ ] Web UI for managing config
