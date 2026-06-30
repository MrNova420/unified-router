from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from .config import load_config
from .registry import build_providers
from .router import Router

logger = logging.getLogger(__name__)

router_instance: Router | None = None


class ChatRequest(BaseModel):
    model: str
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global router_instance
    config = load_config()
    providers = build_providers(config)
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
    yield
    if router_instance:
        await router_instance.close()


app = FastAPI(
    title="Unified Router",
    version="0.4.0",
    lifespan=lifespan,
)


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

    try:
        if body.stream:
            async def gen():
                try:
                    async for chunk in router_instance.route_stream(
                        model=body.model,
                        messages=body.messages,
                        **kwargs,
                    ):
                        yield chunk
                except Exception as e:
                    import json as _json
                    err = {"error": {"message": str(e), "type": "router_error"}}
                    yield (f"data: {_json.dumps(err)}\n\n").encode()
            return StreamingResponse(gen(), media_type="text/event-stream")

        result = await router_instance.route(
            model=body.model,
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
    return {
        "providers": provs,
        "cache": {
            "hits": router_instance._cache_hits if hasattr(router_instance, "_cache_hits") else 0,
            "misses": router_instance._cache_misses if hasattr(router_instance, "_cache_misses") else 0,
            "size": len(router_instance._cache),
        },
    }


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
<div class="card"><a href="/docs">API Docs (Swagger)</a> | <a href="/v1/models">/v1/models</a> | <a href="/v1/stats">/v1/stats (JSON)</a></div>
<div class="card" id="stats"></div>
<div class="card" id="models"></div>
<script>
async function poll(){
  try{
    const s = await fetch('/v1/stats'); const sj = await s.json();
    const ps = sj.providers||{}; const c = sj.cache||{};
    let rows = Object.entries(ps).map(([n,v])=>{
      const st = v.rate_limited ? '<span class=warn>RATE LIMITED</span>' : '<span class=stat>OK</span>';
      return `<tr><td>${n}</td><td>${v.requests}</td><td class=err>${v.errors}</td><td>${v.tokens}</td><td>${v.latency_ema_ms}ms</td><td>${st}</td></tr>`;
    }).join('');
    document.getElementById('stats').innerHTML = '<h2>Provider Stats</h2><table><tr><th>Provider</th><th>Reqs</th><th>Errors</th><th>Tokens</th><th>Latency</th><th>Status</th></tr>'+rows+`</table><p>Cache: ${c.hits||0} hits / ${c.misses||0} misses | ${c.size||0} entries</p>`;
  }catch(e){document.getElementById('stats').innerHTML='<p class=err>'+e+'</p>'}
  try{
    const m = await fetch('/v1/models'); const mj = await m.json();
    const ids = (mj.data||[]).slice(0,100).map(x=>`<li>${x.id} <span class=warn>(${x.owned_by})</span></li>`).join('');
    document.getElementById('models').innerHTML = '<h2>Models (first 100 of '+(mj.data||[]).length+')</h2><ul>'+ids+'</ul>';
  }catch(e){document.getElementById('models').innerHTML='<p class=err>'+e+'</p>'}
}
poll(); setInterval(poll, 3000);
</script></body></html>"""


@app.get("/admin")
async def admin():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_ADMIN_HTML)


def create_app() -> FastAPI:
    return app
