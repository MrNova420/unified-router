from __future__ import annotations

import logging
import signal
import sys
from contextlib import asynccontextmanager
from typing import Any
import asyncio

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, field_validator

from .config import load_config, CONFIG_DIR
from .registry import build_providers
from .router import Router
from .observability import new_trace, current_trace, setup_logging
from .provider import ProviderError, RateLimitError, AuthError
from .queue import RequestQueue

logger = logging.getLogger(__name__)

router_instance: Router | None = None
_shutdown_event: Any = None
_config_mtime: float = 0
request_queue: RequestQueue | None = None


async def _reload_providers():
    global router_instance
    if not router_instance:
        return
    config = load_config()
    providers = build_providers(config)
    if not providers:
        logger.warning("Reload produced zero providers — keeping current config")
        return
    old = router_instance
    router_instance = Router(
        providers,
        config.get("priority", old.priority),
        strategy=config.get("strategy", old.strategy),
        model_pinning=config.get("model_pinning", old.model_pinning),
        enable_cache=config.get("cache", {}).get("enabled", old.enable_cache),
        cache_ttl=config.get("cache", {}).get("ttl", old.cache_ttl),
        load_balance_weights=config.get("load_balance_weights", old.load_balance_weights),
    )
    await router_instance.fetch_all_models(force=True)
    await old.close()
    logger.info("Hot reload: %d providers, %d models", len(providers), len(router_instance._all_models))


class ChatRequest(BaseModel):
    model: str | None = "auto"
    messages: list[dict[str, Any]]
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool | None = False
    stop: str | list[str] | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    seed: int | None = None
    extra_body: dict[str, Any] | None = None

    @field_validator("messages")
    @classmethod
    def messages_not_empty(cls, v):
        if not v:
            raise ValueError("messages must not be empty")
        return v

    @field_validator("temperature")
    @classmethod
    def temp_range(cls, v):
        if v is not None and (v < 0 or v > 2):
            raise ValueError("temperature must be between 0 and 2")
        return v

    @field_validator("max_tokens")
    @classmethod
    def max_tokens_range(cls, v):
        if v is not None and (v < 1 or v > 128000):
            raise ValueError("max_tokens must be between 1 and 128000")
        return v


@asynccontextmanager
async def lifespan(app: FastAPI):
    global router_instance, _shutdown_event
    import asyncio
    _shutdown_event = asyncio.Event()

    config = load_config()
    setup_logging(config.get("server", {}).get("log_level", "info"))
    providers = build_providers(config)

    if not providers:
        logger.error(
            "No providers configured! Set at least one API key. "
            "Run 'unified-router init' or set env vars like OPENROUTER_API_KEY."
        )
        logger.warning("Starting anyway — requests will fail until a provider is configured.")

    priority = config.get("priority", [])
    router_instance = Router(
        providers,
        priority,
        strategy=config.get("strategy", "priority"),
        model_pinning=config.get("model_pinning"),
        enable_cache=config.get("cache", {}).get("enabled", False),
        cache_ttl=config.get("cache", {}).get("ttl", 3600),
        load_balance_weights=config.get("load_balance_weights"),
    )
    await router_instance.fetch_all_models(force=True)
    logger.info(
        "Unified Router started with %d providers, %d models",
        len(providers),
        len(router_instance._all_models),
    )

    async def _watch_config():
        global _config_mtime
        cfg_path = CONFIG_DIR / "config.yml"
        if cfg_path.exists():
            _config_mtime = cfg_path.stat().st_mtime
        while not _shutdown_event.is_set():
            await asyncio.sleep(5)
            if not cfg_path.exists():
                continue
            mtime = cfg_path.stat().st_mtime
            if mtime != _config_mtime:
                _config_mtime = mtime
                logger.info("Config file changed — hot reloading")
                try:
                    await _reload_providers()
                except Exception as e:
                    logger.error("Hot reload failed: %s", e)

    watcher_task = asyncio.create_task(_watch_config())

    global request_queue
    request_queue = RequestQueue(max_size=100, worker_count=10)
    await request_queue.start()

    yield
    _shutdown_event.set()
    watcher_task.cancel()
    if request_queue:
        await request_queue.stop()
    if router_instance:
        await router_instance.close()
        router_instance = None


def create_app() -> FastAPI:
    _app = FastAPI(
        title="Unified Router",
        version="2.0.0",
        lifespan=lifespan,
    )
    _app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @_app.middleware("http")
    async def trace_middleware(request: Request, call_next):
        trace = new_trace()
        logger.info("Request %s %s", request.method, request.url.path)
        start = __import__("time").time()
        response = await call_next(request)
        elapsed = (__import__("time").time() - start) * 1000
        logger.info(
            "Request %s %s completed in %.0fms (trace: %s)",
            request.method, request.url.path, elapsed, trace.request_id,
        )
        response.headers["X-Request-ID"] = trace.request_id
        return response

    @_app.exception_handler(ProviderError)
    @_app.exception_handler(RateLimitError)
    @_app.exception_handler(AuthError)
    async def provider_error_handler(request: Request, exc: Exception):
        status = 503
        err_type = "provider_error"
        if isinstance(exc, AuthError):
            status = 401
            err_type = "auth_error"
        elif isinstance(exc, RateLimitError):
            status = 429
            err_type = "rate_limit_error"
        return JSONResponse(
            status_code=status,
            content={"error": {"message": str(exc), "type": err_type}},
        )

    @_app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error")
        return JSONResponse(
            status_code=500,
            content={"error": {"message": "Internal server error", "type": "internal_error"}},
        )

    return _app


app = create_app()


@app.get("/v1/models")
async def list_models():
    if not router_instance:
        raise HTTPException(503, "Router not initialized")
    models = await router_instance.fetch_all_models()
    return {
        "object": "list",
        "data": [
            {
                "id": m["id"],
                "object": "model",
                "created": 0,
                "owned_by": m.get("provider", "unknown"),
            }
            for m in models
        ],
    }


@app.post("/v1/chat/completions")
async def chat_completion(body: ChatRequest, request: Request):
    if not router_instance:
        raise HTTPException(503, "Router not initialized")

    kwargs = {}
    for key in ("temperature", "top_p", "max_tokens", "stop", "frequency_penalty",
                 "presence_penalty", "seed"):
        val = getattr(body, key, None)
        if val is not None:
            kwargs[key] = val

    if body.extra_body:
        kwargs.update(body.extra_body)

    model_name = body.model or "auto"
    is_auto = model_name.lower() == "auto"

    try:
        if body.stream:
            async def gen():
                try:
                    if is_auto:
                        async for chunk in router_instance.route_auto_stream(
                            messages=body.messages,
                            **kwargs,
                        ):
                            yield chunk
                    else:
                        async for chunk in router_instance.route_stream(
                            model=model_name,
                            messages=body.messages,
                            **kwargs,
                        ):
                            yield chunk
                except Exception as e:
                    import json as _json
                    err = {"error": {"message": str(e), "type": "router_error"}}
                    yield (f"data: {_json.dumps(err)}\n\n").encode()
            return StreamingResponse(gen(), media_type="text/event-stream")

        if is_auto:
            result = await router_instance.route_auto(
                messages=body.messages,
                **kwargs,
            )
        else:
            result = await router_instance.route(
                model=model_name,
                messages=body.messages,
                **kwargs,
            )
        return result
    except Exception as e:
        logger.exception("Routing failed")
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "message": str(e),
                    "type": "router_error",
                }
            },
        )


@app.get("/v1/stats")
async def stats():
    if not router_instance:
        raise HTTPException(503, "Router not initialized")
    provs = router_instance.stats()
    result = {
        "providers": provs,
        "cache": {
            "hits": router_instance._cache_hits if hasattr(router_instance, "_cache_hits") else 0,
            "misses": router_instance._cache_misses if hasattr(router_instance, "_cache_misses") else 0,
            "size": len(router_instance._cache),
        },
    }
    if request_queue:
        result["queue"] = request_queue.stats()
    return result


_ADMIN_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Unified Router Admin</title>
<style>
body{font-family:system-ui;background:#0d1117;color:#c9d1d9;margin:0;padding:20px}
h1{color:#58a6ff}.card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;margin:12px 0}
.pname{font-weight:bold;color:#79c0ff}.stat{color:#7ee787}
.err{color:#ff7b72}.warn{color:#d29922}table{width:100%;border-collapse:collapse}
td,th{text-align:left;padding:6px 10px;border-bottom:1px solid #21262d}
th{color:#8b949e}a{color:#58a6ff}
</style></head><body>
<h1>Unified Router Admin</h1>
<div class="card"><a href="/docs">API Docs (Swagger)</a> | <a href="/v1/models">/v1/models</a> | <a href="/v1/stats">/v1/stats (JSON)</a> | <a href="/settings">/settings</a> | <a href="/reload" onclick="fetch('/reload',{method:'POST'}).then(r=>r.json()).then(d=>alert(JSON.stringify(d)));return false;">Reload Config</a></div>
<div class="card" id="stats"></div>
<div class="card" id="models"></div>
<script>
async function poll(){
  try{
    const s = await fetch('/v1/stats'); const sj = await s.json();
    const ps = sj.providers||{}; const c = sj.cache||{};
    let rows = Object.entries(ps).map(([n,v])=>{
      const st = v.rate_limited ? '<span class=warn>RATE LIMITED</span>' : v.circuit_state === 'OPEN' ? '<span class=err>CIRCUIT OPEN</span>' : '<span class=stat>OK</span>';
      const cb = v.circuit_state || 'CLOSED';
      return `<tr><td>${n}</td><td>${v.requests}</td><td class=err>${v.errors}</td><td>${v.tokens}</td><td>${v.latency_ema_ms}ms</td><td>${st}</td><td>${cb}</td></tr>`;
    }).join('');
    document.getElementById('stats').innerHTML = '<h2>Provider Stats</h2><table><tr><th>Provider</th><th>Reqs</th><th>Errors</th><th>Tokens</th><th>Latency</th><th>Status</th><th>Circuit</th></tr>'+rows+`</table><p>Cache: ${c.hits||0} hits / ${c.misses||0} misses | ${c.size||0} entries</p>`;
  }catch(e){document.getElementById('stats').innerHTML='<p class=err>'+e+'</p>'}
  try{
    const m = await fetch('/v1/models'); const mj = await m.json();
    const ids = (mj.data||[]).slice(0,100).map(x=>`<li>${x.id} <span class=warn>(${x.owned_by})</span></li>`).join('');
    document.getElementById('models').innerHTML = '<h2>Models (first 100 of '+(mj.data||[]).length+')</h2><ul>'+ids+'</ul>';
  }catch(e){document.getElementById('models').innerHTML='<p class=err>'+e+'</p>'}
}
poll(); setInterval(poll, 3000);
</script></body></html>"""


_SETTINGS_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8"><title>Unified Router Settings</title>
<style>
body{font-family:system-ui;background:#0d1117;color:#c9d1d9;margin:0;padding:20px}
h1{color:#58a6ff}.card{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:16px;margin:12px 0}
.btn{background:#238636;color:white;border:none;padding:8px 16px;border-radius:4px;cursor:pointer}
.btn:hover{background:#2ea043}input,select{background:#0d1117;color:#c9d1d9;border:1px solid #30363d;padding:8px;border-radius:4px;color:white}
.table{width:100%;border-collapse:collapse}.table th,.table td{border:1px solid #30363d;padding:8px;text-align:left}
</style></head><body>
<h1>Unified Router Settings</h1>
<div class="card">
<h2>Server Settings</h2>
<form id="serverForm">
  <label>Host: <input name="host" /> </label>
  <label>Port: <input name="port" type="number" /> </label>
  <label>Log Level:
    <select name="log_level">
      <option value="debug">debug</option><option value="info">info</option><option value="warning">warning</option>
    </select>
  </label>
  <button type="submit" class="btn">Save Server</button>
</form>
</div>

<div class="card">
<h2>Providers</h2>
<p>Configure API keys for each provider.</p>
<div id="providers"></div>
<button id="saveAll" class="btn">Save All Keys</button>
</div>

<script>
const apiBase = window.location.origin;
async function load() {
  const r = await fetch(apiBase + '/settings/api');
  const d = await r.json();
  document.querySelector('[name=host]').value = d.server?.host || '127.0.0.1';
  document.querySelector('[name=port]').value = d.server?.port || 3333;
  document.querySelector('[name=log_level]').value = d.server?.log_level || 'info';
  const provDiv = document.getElementById('providers');
  provDiv.innerHTML = '<table class=table><tr><th>Provider</th><th>API Key</th><th>Status</th></tr>';
  for (const [name, p] of Object.entries(d.providers || {})) {
    provDiv.innerHTML += `<tr>
      <td>${name}</td>
      <td><input type="password" data-name="${name}" value="${p.api_key||''}" placeholder="API Key" style="width:100%" /></td>
      <td>${p.configured ? '✅' : '❌'}</td>
    </tr>`;
  }
  provDiv.innerHTML += '</table>';
}
document.getElementById('serverForm').onsubmit = async e => {
  e.preventDefault();
  const r = await fetch(apiBase + '/settings/server', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      host: document.querySelector('[name=host]').value,
      port: parseInt(document.querySelector('[name=port]').value),
      log_level: document.querySelector('[name=log_level]').value
    })
  });
  alert(await r.text());
};
document.getElementById('saveAll').onclick = async () => {
  const keys = {};
  document.querySelectorAll('input[data-name]').forEach(inp => {
    keys[inp.dataset.name] = inp.value;
  });
  const r = await fetch(apiBase + '/settings/keys', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({keys})
  });
  alert(await r.text());
};
load(); setInterval(load, 10000);
</script></body></html>"""


@app.get("/health")
async def health():
    if not router_instance:
        return JSONResponse({"status": "initializing"}, status_code=503)
    active = router_instance.get_active_providers()
    total_configured = sum(1 for p in router_instance.providers.values() if p.is_configured)
    deep = await router_instance.deep_health()
    ok_count = sum(1 for v in deep.values() if v.get("status") == "ok")
    return {
        "status": "ok" if ok_count > 0 else "degraded",
        "providers_configured": total_configured,
        "providers_active": len(active),
        "providers_rate_limited": total_configured - len(active),
        "models_cached": len(router_instance._all_models),
        "providers": deep,
    }


@app.post("/reload")
async def reload_config():
    if not router_instance:
        raise HTTPException(503, "Router not initialized")
    try:
        await _reload_providers()
        return {"status": "reloaded", "providers": len(router_instance.providers), "models": len(router_instance._all_models)}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": {"message": str(e), "type": "reload_error"}})


@app.get("/admin")
async def admin():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_ADMIN_HTML)


@app.get("/settings")
async def settings_page():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_SETTINGS_HTML)


@app.get("/settings/api")
async def get_settings_api():
    if not router_instance:
        raise HTTPException(503, "Router not initialized")
    config = load_config()
    providers_status = {}
    for name, prov in router_instance.providers.items():
        providers_status[name] = {
            "api_key": prov.mask_api_key(),
            "configured": prov.is_configured,
        }
    return {
        "server": config.get("server", {}),
        "providers": providers_status,
        "priority": config.get("priority", []),
    }


@app.post("/settings/server")
async def save_server(req: Request):
    body = await req.json()
    import yaml
    cfg_path = CONFIG_DIR / "config.yml"
    config = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    config.setdefault("server", {}).update(body)
    cfg_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return {"status": "saved"}


@app.post("/settings/keys")
async def save_keys(req: Request):
    body = await req.json()
    keys = body.get("keys", {})
    import yaml
    cfg_path = CONFIG_DIR / "config.yml"
    config = yaml.safe_load(cfg_path.read_text()) if cfg_path.exists() else {}
    provs = config.setdefault("providers", {})
    for name, key in keys.items():
        if name in provs:
            provs[name]["api_key"] = key
    cfg_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return {"status": "saved"}