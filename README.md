# Unified Router

**One endpoint to rule them all.** Route LLM requests across every free provider with automatic fallback.

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

## Supported Providers

| Provider | Free Tier | Get Key |
|----------|-----------|---------|
| OpenRouter | 20 req/min, 50 req/day | [openrouter.ai](https://openrouter.ai/settings/keys) |
| Groq | 1000-14000 req/day | [console.groq.com](https://console.groq.com/keys) |
| Cerebras | 30 req/min, 14k req/day | [inference.cerebras.ai](https://inference.cerebras.ai/) |
| Cloudflare Workers AI | 10k neurons/day | [cloudflare.com](https://dash.cloudflare.com/) |
| NVIDIA NIM | 40 req/min | [build.nvidia.com](https://build.nvidia.com) |
| Google Gemini | 20-1500 req/day | [aistudio.google.com](https://aistudio.google.com/app/apikey) |
| Mistral AI | 1B tokens/month | [console.mistral.ai](https://console.mistral.ai/api-keys/) |
| Cohere | 1000 req/month | [dashboard.cohere.com](https://dashboard.cohere.com/api-keys) |
| HuggingFace | $0.10/mo credits | [huggingface.co](https://huggingface.co/settings/tokens) |
| DeepSeek | Paid (cheap) | [platform.deepseek.com](https://platform.deepseek.com/api_keys) |
| GitHub Models | Free with Copilot | [github.com/settings/tokens](https://github.com/settings/tokens) |

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

All provider keys can be set via environment variables. The router auto-detects them.

```bash
export OPENROUTER_API_KEY="sk-or-..."
export GROQ_API_KEY="gsk_..."
export CEREBRAS_API_KEY="cerebras_..."
export CLOUDFLARE_API_TOKEN="..."
export CLOUDFLARE_ACCOUNT_ID="..."
export NVIDIA_API_KEY="nvapi-..."
export GEMINI_API_KEY="AIza..."
export MISTRAL_API_KEY="..."
export COHERE_API_KEY="..."
export HF_TOKEN="hf_..."
export DEEPSEEK_API_KEY="sk-..."
export GITHUB_TOKEN="ghp_..."

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
  # ...

providers:
  openrouter:
    base_url: "https://openrouter.ai/api/v1"
    api_key: "${OPENROUTER_API_KEY}"
```

Values like `${VAR_NAME}` are resolved from environment variables.

## Architecture

```
┌─────────────┐     ┌─────────────────────────────────────┐     ┌──────────────┐
│  OpenCode   │────▶│  Unified Router (localhost:3333)    │────▶│  OpenRouter  │
│  Any Client │     │                                     │     │  Groq        │
└─────────────┘     │  /v1/chat/completions               │     │  Cerebras    │
                    │  /v1/models                         │     │  Cloudflare  │
                    │                                     │     │  NVIDIA      │
                    │  Router → Provider A → 429?         │     │  Gemini      │
                    │         → Provider B → 200! ✓       │     │  Mistral     │
                    └─────────────────────────────────────┘     │  ...         │
                                                                └──────────────┘
```

## Development

```bash
git clone https://github.com/mrnova420/unified-router
cd unified-router
pip install -e .
unified-router init
unified-router start
```

## Roadmap

- [ ] Per-model provider pinning
- [ ] Load balancing (use multiple providers simultaneously)
- [ ] Usage dashboard (rich terminal UI)
- [ ] Request/response caching
- [ ] Streaming support
- [ ] Prompt template optimization per provider
- [ ] Plugin system for custom providers
- [ ] Web UI for managing config
