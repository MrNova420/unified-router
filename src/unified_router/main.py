from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
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
    router_instance = Router(providers, priority)
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
    version="0.1.0",
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


def create_app() -> FastAPI:
    return app
