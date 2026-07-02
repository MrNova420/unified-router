from __future__ import annotations

import logging
import os
import signal
import sys
from contextlib import asynccontextmanager
from typing import Any
import asyncio

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from pydantic import BaseModel, field_validator

from .config import load_config, CONFIG_DIR, CONFIG_FILE, get_provider_info, PROVIDER_TYPE_BADGES, get_router_key
from .registry import build_providers, load_registry
from .router import Router
from .observability import new_trace, current_trace, setup_logging
from .provider import ProviderError, RateLimitError, AuthError
from .queue import RequestQueue
from .usage_stats import get_usage_stats

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
    
    # Write PID file
    pid_file = CONFIG_DIR / "router.pid"
    pid_file.write_text(str(os.getpid()))

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
    
    # Remove PID file
    pid_file = CONFIG_DIR / "router.pid"
    if pid_file.exists():
        pid_file.unlink()

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
    async def auth_middleware(request: Request, call_next):
        path = request.url.path
        if path.startswith("/v1/"):
            auth_header = request.headers.get("authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header[7:]
            else:
                token = auth_header.strip()
            expected = get_router_key()
            if token != expected:
                return JSONResponse(
                    status_code=401,
                    content={"error": {"message": "Invalid router API key", "type": "auth_error"}},
                    headers={"WWW-Authenticate": "Bearer"},
                )
        return await call_next(request)

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


@app.get("/")
async def root():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_page("dashboard", _LANDING_BODY))


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


_COMMON_HEAD = """<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<script src="https://cdn.tailwindcss.com"></script>
<script>tailwind.config={darkMode:'class',theme:{extend:{colors:{
  brand:'#6366f1',surface:'#0f172a',card:'#1e293b',border:'#334155',
  ok:'#22c55e',warn:'#f59e0b',err:'#ef4444',info:'#3b82f6'
}}}}</script>
<style>body{background:#0f172a}</style>"""

_SIDEBAR = """<nav class="fixed left-0 top-0 h-full w-56 bg-card border-r border-border flex flex-col z-50">
  <div class="p-5 border-b border-border">
    <h1 class="text-xl font-bold text-white tracking-tight">Unified Router</h1>
    <span class="text-xs text-gray-500">v2.0.0</span>
  </div>
  <div class="flex-1 py-4 space-y-1 px-3">
    <a href="/" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium SIDEBAR_DASHBOARD_CLASS">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4"/></svg>
      Dashboard
    </a>
    <a href="/admin" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium SIDEBAR_ADMIN_CLASS">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
      Providers
    </a>
    <a href="/analytics" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium SIDEBAR_ANALYTICS_CLASS">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v6a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/></svg>
      Analytics
    </a>
    <a href="/settings" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium SIDEBAR_SETTINGS_CLASS">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.573-1.066z"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
      Settings
    </a>
    <a href="/docs" class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-gray-400 hover:text-white hover:bg-surface">
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>
      API Docs
    </a>
  </div>
  <div class="p-4 border-t border-border">
    <button onclick="fetch('/reload',{method:'POST'}).then(r=>r.json()).then(d=>{showToast(d.status==='reloaded'?'Config reloaded':'Reload failed','ok')}).catch(()=>showToast('Reload failed','err'))" class="w-full py-2 px-3 rounded-lg bg-brand/20 text-brand text-sm font-medium hover:bg-brand/30 transition-colors">Reload Config</button>
  </div>
</nav>"""

_TOAST_JS = """<div id="toast" class="fixed top-4 right-4 z-[100] hidden"></div>
<script>
function showToast(msg,type='ok'){
  const el=document.getElementById('toast');
  const colors={ok:'bg-ok/20 border-ok text-ok',err:'bg-err/20 border-err text-err',warn:'bg-warn/20 border-warn text-warn'};
  el.className='fixed top-4 right-4 z-[100] border rounded-lg px-4 py-3 text-sm font-medium shadow-lg '+(colors[type]||colors.ok);
  el.textContent=msg;el.classList.remove('hidden');
  setTimeout(()=>el.classList.add('hidden'),3000);
}
</script>"""

_POLL_JS = """let _pollTimers=[];
function startPoll(fn,ms=3000){_pollTimers.forEach(t=>clearInterval(t));_pollTimers=[];fn();const id=setInterval(fn,ms);_pollTimers.push(id);}"""


def _make_sidebar(active: str) -> str:
    classes = {
        "dashboard": "text-gray-400 hover:text-white hover:bg-surface",
        "admin": "text-gray-400 hover:text-white hover:bg-surface",
        "analytics": "text-gray-400 hover:text-white hover:bg-surface",
        "settings": "text-gray-400 hover:text-white hover:bg-surface",
    }
    classes[active] = "bg-brand/20 text-brand"
    return (_SIDEBAR
        .replace("SIDEBAR_DASHBOARD_CLASS", classes["dashboard"])
        .replace("SIDEBAR_ADMIN_CLASS", classes["admin"])
        .replace("SIDEBAR_ANALYTICS_CLASS", classes["analytics"])
        .replace("SIDEBAR_SETTINGS_CLASS", classes["settings"]))


def _page(active: str, body: str) -> str:
    return ("""<!DOCTYPE html>
<html lang="en" class="dark"><head>""" + _COMMON_HEAD + """<title>Unified Router</title></head>
<body class="text-gray-200 min-h-screen">""" + _make_sidebar(active) + _TOAST_JS + _POLL_JS + """<div class="ml-56">""" + body + """</div></body></html>""")


_LANDING_BODY = """
  <header class="flex items-center justify-between px-8 py-6 border-b border-border">
    <div><h2 class="text-2xl font-bold text-white">Dashboard</h2><p class="text-gray-500 text-sm mt-1">System overview & health</p></div>
    <div id="health-badge" class="flex items-center gap-2"><span class="inline-block w-2 h-2 rounded-full bg-gray-600 animate-pulse"></span><span class="text-sm text-gray-500">Loading...</span></div>
  </header>
  <div class="px-8 py-6 space-y-6">
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" id="stat-cards"></div>
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="bg-card rounded-xl border border-border p-5">
        <h3 class="text-sm font-semibold text-gray-400 mb-4">Connect OpenCode</h3>
        <div class="space-y-2 text-sm">
          <div class="flex items-start gap-3"><span class="flex-shrink-0 w-6 h-6 rounded-full bg-brand/20 text-brand text-xs flex items-center justify-center font-bold">1</span><div><p class="text-white font-medium">In OpenCode desktop, run <code class="text-info">/connect</code></p></div></div>
          <div class="flex items-start gap-3"><span class="flex-shrink-0 w-6 h-6 rounded-full bg-brand/20 text-brand text-xs flex items-center justify-center font-bold">2</span><div><p class="text-white font-medium">Choose <code class="text-info">Other</code> (Custom provider)</p></div></div>
          <div class="flex items-start gap-3"><span class="flex-shrink-0 w-6 h-6 rounded-full bg-brand/20 text-brand text-xs flex items-center justify-center font-bold">3</span><div><p class="text-white font-medium">Fill in the fields:</p>
            <div class="mt-2 space-y-1.5 text-xs">
              <div><span class="text-gray-500">Provider ID:</span> <code class="text-info font-mono">unified-router</code></div>
              <div><span class="text-gray-500">Display name:</span> <code class="text-info font-mono">Unified Router</code></div>
              <div><span class="text-gray-500">Base URL:</span> <code class="text-info font-mono">http://localhost:3333/v1</code></div>
              <div><span class="text-gray-500">API key:</span> <code id="router-key-display" class="text-info font-mono select-all">Loading...</code></div>
              <div><span class="text-gray-500">Models:</span> <span class="text-gray-500">leave empty</span></div>
              <div><span class="text-gray-500">Headers:</span> <span class="text-gray-500">leave empty</span></div>
            </div>
          </div></div>
          <div class="flex items-start gap-3"><span class="flex-shrink-0 w-6 h-6 rounded-full bg-brand/20 text-brand text-xs flex items-center justify-center font-bold">4</span><div><p class="text-white font-medium">Models auto-populate from <code class="text-info">/v1/models</code></p></div></div>
        </div>
      </div>
      <div class="bg-card rounded-xl border border-border p-5">
        <h3 class="text-sm font-semibold text-gray-400 mb-4">Provider Overview</h3>
        <div id="provider-badges" class="flex flex-wrap gap-2"></div>
      </div>
    </div>
    <div class="bg-card rounded-xl border border-border p-5">
      <h3 class="text-sm font-semibold text-gray-400 mb-4">Recent Models <span id="model-count" class="text-gray-600"></span></h3>
      <div id="model-grid" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-2 max-h-64 overflow-y-auto"></div>
    </div>
  </div>

<script>
async function loadDashboard(){
  try {
    const [hR, sR, mR, kR] = await Promise.all([
      fetch('/health'),
      fetch('/v1/stats'),
      fetch('/v1/models'),
      fetch('/router-key')
    ]);
    const [h, s, m, k] = await Promise.all([hR.json(), sR.json(), mR.json(), kR.json()]);
    
    document.getElementById('router-key-display').textContent = k.key;

    const hc=h.providers_configured||0,ha=h.providers_active||0,hm=h.models_cached||0;
    const hs=h.status||'unknown';
    const hbadge=hs==='ok'?'ok':hs==='degraded'?'warn':'err';
    document.getElementById('health-badge').innerHTML=
      '<span class="inline-block w-2.5 h-2.5 rounded-full bg-'+hbadge+' animate-pulse"></span>'+
      '<span class="text-sm text-'+hbadge+' font-medium capitalize">'+hs+'</span>';
    const ps=s.providers||{},c=s.cache||{},q=s.queue||{};
    const totalReqs=Object.values(ps).reduce((a,v)=>a+(v.requests||0),0);
    const totalErrs=Object.values(ps).reduce((a,v)=>a+(v.errors||0),0);
    const totalTokens=Object.values(ps).reduce((a,v)=>a+(v.tokens||0),0);
    const avgLat=Object.values(ps).length?Math.round(Object.values(ps).reduce((a,v)=>a+(v.latency_ema_ms||0),0)/Object.values(ps).length):0;
    document.getElementById('stat-cards').innerHTML=[
      dCard('Providers',ha+'/'+hc,'active','#6366f1'),
      dCard('Models',hm,'cached','#3b82f6'),
      dCard('Requests',totalReqs.toLocaleString(),'total','#22c55e'),
      dCard('Avg Latency',avgLat+'ms','#f59e0b'),
      dCard('Errors',totalErrs.toLocaleString(),'total','#ef4444'),
      dCard('Tokens',totalTokens.toLocaleString(),'total','#8b5cf6'),
      dCard('Cache Hits',c.hits||0,'hit rate #','#06b6d4'),
      dCard('Queue',q.pending||0+'/'+(q.size||100),'pending','#f97316'),
    ].join('');
    const badges=Object.entries(ps).map(([n,v])=>{
      let cls='bg-gray-700 text-gray-400';
      if(v.circuit_state==='OPEN')cls='bg-err/20 text-err';
      else if(v.rate_limited)cls='bg-warn/20 text-warn';
      else cls='bg-ok/20 text-ok';
      return '<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium '+cls+'"><span class="w-1.5 h-1.5 rounded-full bg-current opacity-60"></span>'+n+'</span>';
    }).join('');
    document.getElementById('provider-badges').innerHTML=badges||'<span class="text-gray-600 text-sm">No providers</span>';
    const models=(m.data||[]);
    document.getElementById('model-count').textContent='('+models.length+')';
    document.getElementById('model-grid').innerHTML=models.slice(0,120).map(x=>
      '<div class="px-2.5 py-1.5 bg-surface rounded-lg text-xs text-gray-300 truncate" title="'+x.id+'">'+x.id+'</div>'
    ).join('')||'<span class="text-gray-600 text-sm">No models loaded</span>';
  } catch(e){
    console.error(e);
    document.getElementById('health-badge').innerHTML='<span class="text-err text-sm">Connection lost</span>';
  }
}
function dCard(label,value,sub,color){
  return '<div class="bg-card rounded-xl border border-border p-4 hover:border-'+color+'/40 transition-colors">'+
    '<p class="text-xs font-medium text-gray-500 mb-1">'+label+'</p>'+
    '<p class="text-2xl font-bold text-white">'+value+'</p>'+
    '<p class="text-xs text-gray-600 mt-1">'+sub+'</p></div>';
}
startPoll(loadDashboard,5000);
</script>"""

_LANDING_HTML = None  # built dynamically

_ADMIN_BODY = """
  <header class="flex items-center justify-between px-8 py-6 border-b border-border">
    <div><h2 class="text-2xl font-bold text-white">Providers</h2><p class="text-gray-500 text-sm mt-1">Real-time provider status & statistics</p></div>
    <div class="flex items-center gap-3">
      <button onclick="fetch('/reload',{method:'POST'}).then(r=>r.json()).then(d=>showToast(d.status==='reloaded'?'Reloaded OK':'Reload failed')).catch(()=>showToast('Reload failed','err'))" class="px-4 py-2 rounded-lg bg-brand/20 text-brand text-sm font-medium hover:bg-brand/30 transition-colors">Refresh Models</button>
    </div>
  </header>
  <div class="px-8 py-6 space-y-6">
    <div class="grid grid-cols-1 sm:grid-cols-3 gap-4" id="summary-cards"></div>
    <div class="bg-card rounded-xl border border-border overflow-hidden">
      <div class="px-5 py-4 border-b border-border flex items-center justify-between">
        <h3 class="text-sm font-semibold text-white">All Providers</h3>
        <span id="prov-count" class="text-xs text-gray-500"></span>
      </div>
      <div class="overflow-x-auto">
        <table class="w-full text-sm"><thead><tr class="text-left text-gray-500 border-b border-border">
          <th class="px-5 py-3 font-medium">Provider</th>
          <th class="px-5 py-3 font-medium">Requests</th>
          <th class="px-5 py-3 font-medium">Errors</th>
          <th class="px-5 py-3 font-medium">Tokens</th>
          <th class="px-5 py-3 font-medium">Latency</th>
          <th class="px-5 py-3 font-medium">Status</th>
          <th class="px-5 py-3 font-medium">Circuit</th>
        </tr></thead><tbody id="prov-rows"></tbody></table>
      </div>
    </div>
    <div class="bg-card rounded-xl border border-border p-5">
      <h3 class="text-sm font-semibold text-gray-400 mb-3">Cache <span id="cache-info" class="text-gray-600"></span></h3>
      <div class="flex gap-6 text-sm">
        <div><span class="text-gray-500">Hits:</span> <span id="cache-hits" class="text-white font-medium">0</span></div>
        <div><span class="text-gray-500">Misses:</span> <span id="cache-misses" class="text-white font-medium">0</span></div>
        <div><span class="text-gray-500">Entries:</span> <span id="cache-size" class="text-white font-medium">0</span></div>
        <div><span class="text-gray-500">Hit Rate:</span> <span id="cache-rate" class="text-ok font-medium">0%</span></div>
      </div>
    </div>
    <div class="bg-card rounded-xl border border-border p-5">
      <h3 class="text-sm font-semibold text-gray-400 mb-3">Request Queue <span id="queue-info" class="text-gray-600"></span></h3>
      <div class="flex gap-6 text-sm">
        <div><span class="text-gray-500">Pending:</span> <span id="queue-pending" class="text-white font-medium">0</span></div>
        <div><span class="text-gray-500">Completed:</span> <span id="queue-completed" class="text-white font-medium">0</span></div>
        <div><span class="text-gray-500">Rejected:</span> <span id="queue-rejected" class="text-white font-medium">0</span></div>
      </div>
    </div>
    <div class="bg-card rounded-xl border border-border p-5">
      <h3 class="text-sm font-semibold text-gray-400 mb-3">Models <span id="model-count" class="text-gray-600"></span></h3>
      <input id="model-search" type="text" placeholder="Filter models..." class="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand mb-3" />
      <div id="model-list" class="space-y-1 max-h-96 overflow-y-auto"></div>
    </div>
  </div>
<script>
let allModels=[];
function loadAdmin(){
  Promise.all([fetch('/v1/stats'),fetch('/v1/models')])
    .then(([sR,mR])=>Promise.all([sR.json(),mR.json()]))
    .then(([s,m])=>{
      const ps=s.providers||{},c=s.cache||{},q=s.queue||{};
      const totalReqs=Object.values(ps).reduce((a,v)=>a+(v.requests||0),0);
      const totalErrs=Object.values(ps).reduce((a,v)=>a+(v.errors||0),0);
      const totalTokens=Object.values(ps).reduce((a,v)=>a+(v.tokens||0),0);
      document.getElementById('summary-cards').innerHTML=[
        sCard('Total Requests',totalReqs.toLocaleString(),'#22c55e'),
        sCard('Total Errors',totalErrs.toLocaleString(),'#ef4444'),
        sCard('Total Tokens',totalTokens.toLocaleString(),'#8b5cf6'),
      ].join('');
      document.getElementById('prov-count').textContent=Object.keys(ps).length+' configured';
      const rows=Object.entries(ps).map(([n,v])=>{
        let stBadge='<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-ok/20 text-ok"><span class="w-1.5 h-1.5 rounded-full bg-ok"></span>OK</span>';
        if(v.rate_limited)stBadge='<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-warn/20 text-warn"><span class="w-1.5 h-1.5 rounded-full bg-warn"></span>Rate Limited</span>';
        else if(v.circuit_state==='OPEN')stBadge='<span class="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-xs font-medium bg-err/20 text-err"><span class="w-1.5 h-1.5 rounded-full bg-err"></span>Circuit Open</span>';
        let cbBadge='<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-ok/10 text-ok">CLOSED</span>';
        if(v.circuit_state==='OPEN')cbBadge='<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-err/10 text-err">OPEN</span>';
        else if(v.circuit_state==='HALF_OPEN')cbBadge='<span class="px-2 py-0.5 rounded-full text-xs font-medium bg-warn/10 text-warn">HALF-OPEN</span>';
        const errCls=v.errors>0?'text-err':'text-gray-300';
        return '<tr class="border-b border-border/50 hover:bg-surface/50">'+
          '<td class="px-5 py-3 font-medium text-white">'+n+'</td>'+
          '<td class="px-5 py-3">'+(v.requests||0)+'</td>'+
          '<td class="px-5 py-3 '+errCls+'">'+(v.errors||0)+'</td>'+
          '<td class="px-5 py-3">'+(v.tokens||0).toLocaleString()+'</td>'+
          '<td class="px-5 py-3">'+(v.latency_ema_ms||0)+'ms</td>'+
          '<td class="px-5 py-3">'+stBadge+'</td>'+
          '<td class="px-5 py-3">'+cbBadge+'</td></tr>';
      }).join('');
      document.getElementById('prov-rows').innerHTML=rows||'<tr><td colspan="7" class="px-5 py-8 text-center text-gray-600">No providers</td></tr>';
      document.getElementById('cache-hits').textContent=c.hits||0;
      document.getElementById('cache-misses').textContent=c.misses||0;
      document.getElementById('cache-size').textContent=c.size||0;
      const total=(c.hits||0)+(c.misses||0);
      document.getElementById('cache-rate').textContent=total?Math.round((c.hits||0)/total*100)+'%':'0%';
      document.getElementById('queue-pending').textContent=q.pending||0;
      document.getElementById('queue-completed').textContent=q.completed||0;
      document.getElementById('queue-rejected').textContent=q.rejected||0;
      allModels=(m.data||[]).map(x=>({id:x.id,provider:x.owned_by}));
      document.getElementById('model-count').textContent='('+allModels.length+')';
      renderModels();
    }).catch(e=>console.error(e));
}
function renderModels(filter=''){
  const f=filter.toLowerCase();
  const filtered=f?allModels.filter(m=>m.id.toLowerCase().includes(f)):allModels.slice(0,200);
  document.getElementById('model-list').innerHTML=filtered.map(m=>
    '<div class="flex items-center justify-between px-3 py-2 rounded-lg hover:bg-surface transition-colors">'+
    '<span class="text-sm text-gray-300 truncate" title="'+m.id+'">'+m.id+'</span>'+
    '<span class="text-xs text-gray-600 ml-3 flex-shrink-0">'+m.provider+'</span></div>'
  ).join('')||'<div class="text-gray-600 text-sm py-4 text-center">No models found</div>';
}
function sCard(label,val,color){
  return '<div class="bg-card rounded-xl border border-border p-4"><p class="text-xs text-gray-500 mb-1">'+label+'</p><p class="text-2xl font-bold" style="color:'+color+'">'+val+'</p></div>';
}
document.getElementById('model-search').addEventListener('input',e=>renderModels(e.target.value));
startPoll(loadAdmin,3000);
</script>"""

_ADMIN_HTML = None  # built dynamically

_SETTINGS_BODY = """
  <header class="flex items-center justify-between px-8 py-6 border-b border-border">
    <div><h2 class="text-2xl font-bold text-white">Settings</h2><p class="text-gray-500 text-sm mt-1">Configure all providers & server settings</p></div>
  </header>
  <div class="px-8 py-6 space-y-6">
    <div class="bg-card rounded-xl border border-border p-6 max-w-4xl">
      <h3 class="text-sm font-semibold text-white mb-4">Server Configuration</h3>
      <form id="serverForm" class="space-y-4">
        <div class="grid grid-cols-2 gap-4">
          <div><label class="block text-xs text-gray-500 mb-1.5">Host</label><input name="host" class="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-white focus:outline-none focus:border-brand" /></div>
          <div><label class="block text-xs text-gray-500 mb-1.5">Port</label><input name="port" type="number" class="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-white focus:outline-none focus:border-brand" /></div>
        </div>
        <div><label class="block text-xs text-gray-500 mb-1.5">Log Level</label>
          <select name="log_level" class="w-full px-3 py-2 bg-surface border border-border rounded-lg text-sm text-white focus:outline-none focus:border-brand">
            <option value="debug">debug</option><option value="info">info</option><option value="warning">warning</option><option value="error">error</option>
          </select>
        </div>
        <button type="submit" class="px-4 py-2 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand/80 transition-colors">Save Server Settings</button>
      </form>
    </div>

    <div class="bg-card rounded-xl border border-border p-6 max-w-5xl">
      <div class="flex items-center justify-between mb-4">
        <h3 class="text-sm font-semibold text-white">All Providers</h3>
        <span id="key-count" class="text-xs text-gray-500"></span>
      </div>
      <div class="flex gap-2 mb-4">
        <input id="key-search" type="text" placeholder="Filter providers..." class="flex-1 px-3 py-2 bg-surface border border-border rounded-lg text-sm text-white placeholder-gray-600 focus:outline-none focus:border-brand" />
        <select id="type-filter" class="px-3 py-2 bg-surface border border-border rounded-lg text-sm text-white focus:outline-none focus:border-brand">
          <option value="">All Types</option><option value="free">Free</option><option value="phone">Phone Verify</option><option value="credits">Credits</option><option value="paid">Paid</option>
        </select>
        <select id="status-filter" class="px-3 py-2 bg-surface border border-border rounded-lg text-sm text-white focus:outline-none focus:border-brand">
          <option value="">All Status</option><option value="configured">Configured</option><option value="unconfigured">Not Configured</option>
        </select>
      </div>
      <div class="space-y-2" id="provider-keys"></div>
      <div class="mt-5 flex items-center gap-3">
        <button id="saveAll" class="px-4 py-2 rounded-lg bg-brand text-white text-sm font-medium hover:bg-brand/80 transition-colors">Save All Keys</button>
        <button id="saveAndReload" class="px-4 py-2 rounded-lg bg-ok/20 text-ok text-sm font-medium hover:bg-ok/30 transition-colors">Save & Reload Router</button>
        <span id="save-status" class="text-xs text-gray-600"></span>
      </div>
    </div>

    <div class="bg-card rounded-xl border border-border p-6 max-w-4xl">
      <h3 class="text-sm font-semibold text-white mb-3">Priority Order</h3>
      <p id="priority-list" class="text-sm text-gray-400 font-mono"></p>
    </div>

    <div class="bg-card rounded-xl border border-border p-6 max-w-4xl">
      <h3 class="text-sm font-semibold text-white mb-3">Danger Zone</h3>
      <button onclick="if(confirm('Reload config from disk? Unsaved changes will be lost.')){fetch('/reload',{method:'POST'}).then(r=>r.json()).then(d=>{showToast(d.status==='reloaded'?'Config reloaded':'Reload failed');loadSettings();}).catch(()=>showToast('Reload failed','err'))}" class="px-4 py-2 rounded-lg bg-err/20 text-err text-sm font-medium hover:bg-err/30 transition-colors">Force Reload Config</button>
    </div>
  </div>
<script>
const apiBase=window.location.origin;
let allProviders=[];
const TYPE_COLORS={free:'bg-ok/20 text-ok',phone:'bg-warn/20 text-warn',credits:'bg-info/20 text-info',paid:'bg-gray-600/30 text-gray-400'};
const TYPE_LABELS={free:'Free',phone:'Phone',credits:'Credits',paid:'Paid'};
async function loadSettings(){
  const r=await fetch(apiBase+'/settings/api');
  const d=await r.json();
  document.querySelector('[name=host]').value=d.server?.host||'127.0.0.1';
  document.querySelector('[name=port]').value=d.server?.port||3333;
  document.querySelector('[name=log_level]').value=d.server?.log_level||'info';
  allProviders=Object.entries(d.providers||{}).map(([id,p])=>({id,...p}));
  const configured=allProviders.filter(p=>p.configured).length;
  document.getElementById('key-count').textContent=configured+'/'+allProviders.length+' configured';
  document.getElementById('priority-list').textContent=(d.priority||[]).join('  \u2192  ')||'Default priority';
  renderProviderKeys();
}
function renderProviderKeys(){
  const search=(document.getElementById('key-search').value||'').toLowerCase();
  const typeFilter=document.getElementById('type-filter').value;
  const statusFilter=document.getElementById('status-filter').value;
  let filtered=allProviders;
  if(search)filtered=filtered.filter(p=>(p.name||p.id).toLowerCase().includes(search)||(p.env_key||'').toLowerCase().includes(search));
  if(typeFilter)filtered=filtered.filter(p=>p.type===typeFilter);
  if(statusFilter==='configured')filtered=filtered.filter(p=>p.configured);
  else if(statusFilter==='unconfigured')filtered=filtered.filter(p=>!p.configured);
  document.getElementById('provider-keys').innerHTML=filtered.map(p=>{
    const typeCls=TYPE_COLORS[p.type]||TYPE_COLORS.free;
    const typeLabel=TYPE_LABELS[p.type]||p.type;
    const statusDot=p.configured?'bg-ok':'bg-gray-600';
    const statusText=p.configured?'Ready':'Not set';
    const statusCls=p.configured?'text-ok':'text-gray-600';
    const signup=p.signup_url?'<a href="'+p.signup_url+'" target="_blank" class="text-xs text-info hover:underline">Get Key</a>':'';
    const envHint=p.env_key?'<span class="text-[10px] text-gray-600 font-mono">'+p.env_key+'</span>':'';
    const stats=(p.configured&&p.requests)?'<span class="text-[10px] text-gray-600 ml-2">'+p.requests+' reqs \u00B7 '+p.tokens+' tok</span>':'';
    const rl=p.rate_limited?'<span class="text-[10px] text-warn ml-1">RATE LIMITED</span>':'';
    const cs=p.circuit_state==='OPEN'?'<span class="text-[10px] text-err ml-1">CIRCUIT OPEN</span>':'';
    return '<div class="flex items-center gap-3 px-4 py-3 bg-surface rounded-lg">'+
      '<span class="w-2 h-2 rounded-full '+statusDot+' flex-shrink-0"></span>'+
      '<div class="flex flex-col min-w-0 w-40 flex-shrink-0">'+
        '<span class="text-sm text-white font-medium truncate" title="'+(p.name||p.id)+'">'+(p.name||p.id)+'</span>'+
        '<div class="flex items-center gap-1.5">'+envHint+rl+cs+stats+'</div>'+
      '</div>'+
      '<span class="px-2 py-0.5 rounded-full text-[10px] font-medium '+typeCls+' flex-shrink-0">'+typeLabel+'</span>'+
      '<input type="password" data-name="'+p.id+'" value="'+(p.api_key||'')+'" placeholder="sk-..." class="flex-1 px-3 py-1.5 bg-card border border-border rounded-lg text-sm text-white placeholder-gray-700 focus:outline-none focus:border-brand" />'+
      signup+
      '<span class="text-xs '+statusCls+' w-16 text-right flex-shrink-0">'+statusText+'</span></div>';
  }).join('')||'<div class="text-gray-600 text-sm py-4 text-center">No providers match filter</div>';
}
async function saveKeys(){
  const keys={};
  document.querySelectorAll('input[data-name]').forEach(inp=>{keys[inp.dataset.name]=inp.value;});
  try{
    await fetch(apiBase+'/settings/keys',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({keys})});
    showToast('API keys saved');
    loadSettings();
  }catch(e){showToast('Save failed','err');}
}
document.getElementById('serverForm').onsubmit=async e=>{
  e.preventDefault();
  try{
    const r=await fetch(apiBase+'/settings/server',{
      method:'POST',headers:{'Content-Type':'application/json'},
      body:JSON.stringify({host:document.querySelector('[name=host]').value,port:parseInt(document.querySelector('[name=port]').value),log_level:document.querySelector('[name=log_level]').value})
    });
    await r.json();showToast('Server settings saved');
  }catch(e){showToast('Save failed','err');}
};
document.getElementById('saveAll').onclick=saveKeys;
document.getElementById('saveAndReload').onclick=async()=>{await saveKeys();try{await fetch('/reload',{method:'POST'});showToast('Router reloaded with new keys');}catch(e){showToast('Reload failed','err');}};
document.getElementById('key-search').addEventListener('input',renderProviderKeys);
document.getElementById('type-filter').addEventListener('change',renderProviderKeys);
document.getElementById('status-filter').addEventListener('change',renderProviderKeys);
loadSettings();setInterval(loadSettings,15000);
</script>"""

_SETTINGS_HTML = None  # built dynamically

_ANALYTICS_BODY = """
  <header class="flex items-center justify-between px-8 py-6 border-b border-border">
    <div><h2 class="text-2xl font-bold text-white">Analytics</h2><p class="text-gray-500 text-sm mt-1">Lifetime usage, per-provider & model breakdown</p></div>
    <div class="flex gap-2">
      <select id="time-range" class="px-3 py-2 bg-surface border border-border rounded-lg text-sm text-white focus:outline-none focus:border-brand">
        <option value="all">All Time</option><option value="3600">Last Hour</option><option value="86400">Last 24h</option><option value="604800">Last 7d</option>
      </select>
    </div>
  </header>
  <div class="px-8 py-6 space-y-6">
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4" id="lifetime-cards"></div>

    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
      <div class="bg-card rounded-xl border border-border p-5">
        <h3 class="text-sm font-semibold text-white mb-4">Provider Breakdown</h3>
        <div class="overflow-x-auto">
          <table class="w-full text-sm"><thead><tr class="text-left text-gray-500 border-b border-border">
            <th class="px-3 py-2 font-medium">Provider</th>
            <th class="px-3 py-2 font-medium">Requests</th>
            <th class="px-3 py-2 font-medium">Errors</th>
            <th class="px-3 py-2 font-medium">Tokens</th>
            <th class="px-3 py-2 font-medium">Avg Latency</th>
            <th class="px-3 py-2 font-medium">Last Used</th>
          </tr></thead><tbody id="provider-usage-rows"></tbody></table>
        </div>
      </div>

      <div class="bg-card rounded-xl border border-border p-5">
        <h3 class="text-sm font-semibold text-white mb-4">Top Models</h3>
        <div class="overflow-x-auto max-h-80 overflow-y-auto">
          <table class="w-full text-sm"><thead><tr class="text-left text-gray-500 border-b border-border sticky top-0 bg-card">
            <th class="px-3 py-2 font-medium">Model</th>
            <th class="px-3 py-2 font-medium">Requests</th>
            <th class="px-3 py-2 font-medium">Tokens</th>
            <th class="px-3 py-2 font-medium">Errors</th>
            <th class="px-3 py-2 font-medium">Last Used</th>
          </tr></thead><tbody id="model-usage-rows"></tbody></table>
        </div>
      </div>
    </div>

    <div class="bg-card rounded-xl border border-border p-5">
      <h3 class="text-sm font-semibold text-white mb-4">Recent Requests <span id="req-count" class="text-gray-600"></span></h3>
      <div class="overflow-x-auto max-h-96 overflow-y-auto">
        <table class="w-full text-sm"><thead><tr class="text-left text-gray-500 border-b border-border sticky top-0 bg-card">
          <th class="px-3 py-2 font-medium">Time</th>
          <th class="px-3 py-2 font-medium">Provider</th>
          <th class="px-3 py-2 font-medium">Model</th>
          <th class="px-3 py-2 font-medium">Tokens</th>
          <th class="px-3 py-2 font-medium">Latency</th>
          <th class="px-3 py-2 font-medium">Status</th>
        </tr></thead><tbody id="request-log-rows"></tbody></table>
      </div>
    </div>
  </div>
<script>
function loadAnalytics(){
  Promise.all([fetch('/usage'),fetch('/v1/stats')])
    .then(([uR,sR])=>Promise.all([uR.json(),sR.json()]))
    .then(([u,s])=>{
      document.getElementById('lifetime-cards').innerHTML=[
        lCard('Lifetime Requests',u.lifetime_requests.toLocaleString(),'total','#22c55e'),
        lCard('Lifetime Tokens',u.lifetime_tokens.toLocaleString(),'total','#8b5cf6'),
        lCard('Lifetime Errors',u.lifetime_errors.toLocaleString(),'total','#ef4444'),
        lCard('Uptime',formatUptime(u.uptime_seconds),'','#3b82f6'),
      ].join('');

      const provRows=Object.entries(u.providers||{}).sort((a,b)=>b[1].requests-a[1].requests).map(([name,v])=>{
        const avgLat=v.requests?Math.round(v.latency_ms_total/v.requests):0;
        const ago=v.last_used_ago?formatAgo(v.last_used_ago):'Never';
        const errCls=(v.errors||0)>0?'text-err':'text-gray-300';
        return '<tr class="border-b border-border/50 hover:bg-surface/50">'+
          '<td class="px-3 py-2 font-medium text-white">'+name+'</td>'+
          '<td class="px-3 py-2">'+v.requests+'</td>'+
          '<td class="px-3 py-2 '+errCls+'">'+v.errors+'</td>'+
          '<td class="px-3 py-2">'+v.tokens.toLocaleString()+'</td>'+
          '<td class="px-3 py-2">'+avgLat+'ms</td>'+
          '<td class="px-3 py-2 text-gray-500 text-xs">'+ago+'</td></tr>';
      }).join('');
      document.getElementById('provider-usage-rows').innerHTML=provRows||'<tr><td colspan="6" class="px-3 py-8 text-center text-gray-600">No data yet</td></tr>';

      const modelRows=Object.entries(u.models||{}).sort((a,b)=>b[1].requests-a[1].requests).slice(0,50).map(([name,v])=>{
        const ago=v.last_used_ago?formatAgo(v.last_used_ago):'Never';
        const errCls=(v.errors||0)>0?'text-err':'text-gray-300';
        const provList=Object.entries(v.providers||{}).map(([pn,pv])=>pn+'('+pv.requests+')').join(', ');
        return '<tr class="border-b border-border/50 hover:bg-surface/50">'+
          '<td class="px-3 py-2 font-mono text-xs text-white truncate max-w-xs" title="'+name+'\\nvia: '+provList+'">'+name+'</td>'+
          '<td class="px-3 py-2">'+v.requests+'</td>'+
          '<td class="px-3 py-2">'+v.tokens.toLocaleString()+'</td>'+
          '<td class="px-3 py-2 '+errCls+'">'+v.errors+'</td>'+
          '<td class="px-3 py-2 text-gray-500 text-xs">'+ago+'</td></tr>';
      }).join('');
      document.getElementById('model-usage-rows').innerHTML=modelRows||'<tr><td colspan="5" class="px-3 py-8 text-center text-gray-600">No data yet</td></tr>';

      const rangeSec=parseInt(document.getElementById('time-range').value)||0;
      let reqs=u.recent_requests||[];
      if(rangeSec>0){
        const cutoff=(Date.now()/1000)-rangeSec;
        reqs=reqs.filter(r=>r.time>=cutoff);
      }
      document.getElementById('req-count').textContent='('+reqs.length+')';
      const reqRows=reqs.slice().reverse().map(r=>{
        const t=new Date(r.time*1000);
        const timeStr=t.toLocaleTimeString();
        const statusCls=r.status==='ok'?'text-ok':r.status==='rate_limit'?'text-warn':'text-err';
        return '<tr class="border-b border-border/50 hover:bg-surface/50">'+
          '<td class="px-3 py-2 text-xs text-gray-400">'+timeStr+'</td>'+
          '<td class="px-3 py-2">'+r.provider+'</td>'+
          '<td class="px-3 py-2 font-mono text-xs">'+r.model+'</td>'+
          '<td class="px-3 py-2">'+r.tokens+'</td>'+
          '<td class="px-3 py-2">'+r.latency_ms+'ms</td>'+
          '<td class="px-3 py-2 '+statusCls+'">'+r.status+'</td></tr>';
      }).join('');
      document.getElementById('request-log-rows').innerHTML=reqRows||'<tr><td colspan="6" class="px-3 py-8 text-center text-gray-600">No requests yet</td></tr>';
    }).catch(e=>console.error(e));
}
function lCard(label,val,sub,color){
  return '<div class="bg-card rounded-xl border border-border p-4"><p class="text-xs text-gray-500 mb-1">'+label+'</p><p class="text-2xl font-bold" style="color:'+color+'">'+val+'</p>'+(sub?'<p class="text-xs text-gray-600 mt-1">'+sub+'</p>':'')+'</div>';
}
function formatAgo(s){
  if(s<60)return s+'s ago';if(s<3600)return Math.floor(s/60)+'m ago';if(s<86400)return Math.floor(s/3600)+'h ago';return Math.floor(s/86400)+'d ago';
}
function formatUptime(s){
  if(s<60)return s+'s';if(s<3600)return Math.floor(s/60)+'m '+Math.floor(s%60)+'s';if(s<86400)return Math.floor(s/3600)+'h '+Math.floor((s%3600)/60)+'m';return Math.floor(s/86400)+'d '+Math.floor((s%86400)/3600)+'h';
}
document.getElementById('time-range').addEventListener('change',loadAnalytics);
startPoll(loadAnalytics,5000);
</script>"""

_ANALYTICS_HTML = None  # built dynamically


@app.get("/router-key")
async def get_router_key_endpoint():
    from .config import get_router_key
    return {"key": get_router_key()}

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


@app.get("/analytics")
async def analytics():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_page("analytics", _ANALYTICS_BODY))


@app.get("/admin")
async def admin():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_page("admin", _ADMIN_BODY))


@app.get("/settings")
async def settings_page():
    from fastapi.responses import HTMLResponse
    return HTMLResponse(_page("settings", _SETTINGS_BODY))


@app.get("/settings/api")
async def get_settings_api():
    config = load_config()
    registry = load_registry()
    providers_status = {}

    all_registry = {}
    all_registry.update(registry.get("openai_compatible", {}))
    all_registry.update(registry.get("custom", {}))

    for name, reg in all_registry.items():
        prov = router_instance.providers.get(name) if router_instance else None
        providers_status[name] = {
            "name": reg.get("name", name),
            "api_key": prov.mask_api_key() if prov else "",
            "configured": prov.is_configured if prov else bool(config.get("providers", {}).get(name, {}).get("api_key")),
            "available": prov.is_available if prov else False,
            "base_url": reg.get("base_url", ""),
            "signup_url": reg.get("signup_url", ""),
            "free_tier": reg.get("free_tier", ""),
            "type": reg.get("type", "free"),
            "env_key": reg.get("env_key", ""),
            "circuit_state": prov.circuit_breaker.state.name if prov and prov.is_configured else None,
            "rate_limited": prov.is_rate_limited if prov and prov.is_configured else False,
            "requests": prov.request_count if prov else 0,
            "errors": prov.error_count if prov else 0,
            "tokens": prov.token_count if prov else 0,
            "latency_ema_ms": round(prov.latency_ema * 1000, 1) if prov and prov.latency_ema else 0,
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
    registry = load_registry()
    all_registry = {}
    all_registry.update(registry.get("openai_compatible", {}))
    all_registry.update(registry.get("custom", {}))
    for name, key in keys.items():
        if key:
            if name not in provs:
                reg = all_registry.get(name, {})
                provs[name] = {
                    "base_url": reg.get("base_url", ""),
                    "env_key": reg.get("env_key", ""),
                    "api_key": key,
                }
            else:
                provs[name]["api_key"] = key
        elif name in provs:
            provs[name].pop("api_key", None)
    cfg_path.write_text(yaml.dump(config, default_flow_style=False, sort_keys=False))
    return {"status": "saved"}


@app.get("/usage")
async def usage_stats():
    return get_usage_stats().snapshot()