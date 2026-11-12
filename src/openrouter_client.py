"""Cliente OpenAI-compatible contra la API de OpenRouter.

Cada llamada apunta a UN modelo concreto. El failover entre modelos lo
gestiona router.py, no este módulo.
"""

from __future__ import annotations

import os

from openai import OpenAI

BASE_URL = os.getenv("OR_BASE_URL", "https://openrouter.ai/api/v1")
APP_NAME = "mega-free-chat"


class OpenRouterClient:
    def __init__(self, api_key: str) -> None:
        self.client = OpenAI(
            api_key=api_key,
            base_url=BASE_URL,
            default_headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": APP_NAME,
            },
        )

    def chat_stream(self, model_id: str, messages: list[dict]):
        """Devuelve un iterable de fragmentos (streaming) del modelo indicado.

        Lanza openai.APIError / APIConnectionError / etc. en caso de fallo,
        para que el router los capture y pruebe el siguiente modelo.
        """
        resp = self.client.chat.completions.create(
            model=model_id,
            messages=messages,
            stream=True,
        )
        for chunk in resp:
            if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
