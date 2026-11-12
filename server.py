"""Servidor FastAPI de la pasarela de modelos gratuitos.

Sirve la UI web y expone:
  GET  /            -> chat UI
  GET  /api/models  -> estado del pool de modelos gratuitos
  POST /api/chat    -> envío de mensaje con streaming (SSE)
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.models_pool import ModelsPool
from src.openrouter_client import OpenRouterClient
from src.router import FreeModelRouter, RouterError

load_dotenv()

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG", "false").lower() == "true" else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("mega_free_chat.server")

API_KEY = os.getenv("OPENROUTER_API_KEY", "")
if not API_KEY or API_KEY.startswith("sk-or-v1-..."):
    logger.warning("OPENROUTER_API_KEY no configurada o vacía en .env")

BASE_DIR = Path(__file__).parent

pool = ModelsPool(API_KEY)
client = OpenRouterClient(API_KEY)
router = FreeModelRouter(pool, client)

app = FastAPI(title="Mega Free Chat", version="0.1.0")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=100000)
    history: list[dict] = Field(default_factory=list)
    api_key: str | None = None


def sse_payload(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/models")
async def models_status() -> dict:
    return pool.to_payload()


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    messages = list(req.history) + [{"role": "user", "content": req.message}]

    # Si el cliente envía una api_key propia, creamos un router local con ella;
    # si no, usamos la global configurada en .env
    active_router = router
    if req.api_key:
        local_pool = ModelsPool(req.api_key)
        local_client = OpenRouterClient(req.api_key)
        active_router = FreeModelRouter(local_pool, local_client)

    async def event_stream():
        yield sse_payload("status", {"state": "routing"})
        try:
            model_id, stream = active_router.stream(messages)
            yield sse_payload("status", {"state": "streaming", "model": model_id})
            for fragment in stream:
                yield sse_payload("chunk", {"content": fragment})
            yield sse_payload("done", {"model": model_id})
        except RouterError as exc:
            yield sse_payload("error", {"message": str(exc)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Error de servidor")
            yield sse_payload("error", {"message": f"Error interno: {exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
