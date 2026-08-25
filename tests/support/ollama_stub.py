"""Deterministic CI-only Ollama HTTP surface for bootstrap identity/index checks."""

from __future__ import annotations

import hashlib
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

CHAT_MODEL = os.environ.get("OLLAMA_CHAT_MODEL", "ci-chat-not-used")
EMBEDDING_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "ci-embedding-not-used")
CHAT_DIGEST = "sha256:" + "1" * 64
EMBEDDING_DIGEST = "sha256:" + "2" * 64


def _embedding(text: str) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [value / 255 + 0.01 for value in digest[:8]]


class OllamaStubHandler(BaseHTTPRequestHandler):
    server_version = "DataAgentOllamaStub/0.1"

    def _payload(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        decoded = json.loads(raw) if raw else {}
        if not isinstance(decoded, dict):
            raise ValueError("request payload must be an object")
        return decoded

    def _respond(self, payload: dict[str, Any], status: int = 200) -> None:
        encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        if self.path == "/api/version":
            self._respond({"version": "ci-stub-0.1"})
            return
        if self.path == "/api/tags":
            self._respond(
                {
                    "models": [
                        {"name": CHAT_MODEL, "digest": CHAT_DIGEST},
                        {"name": EMBEDDING_MODEL, "digest": EMBEDDING_DIGEST},
                    ]
                }
            )
            return
        self._respond({"error": "not found"}, status=404)

    def do_POST(self) -> None:
        payload = self._payload()
        if self.path == "/api/show":
            model = payload.get("model")
            if model == CHAT_MODEL:
                capabilities = ["completion"]
                family = "ci-chat"
            elif model == EMBEDDING_MODEL:
                capabilities = ["embedding"]
                family = "ci-embedding"
            else:
                self._respond({"error": "model not found"}, status=404)
                return
            self._respond(
                {
                    "capabilities": capabilities,
                    "details": {
                        "family": family,
                        "parameter_size": "stub",
                        "quantization_level": "stub",
                    },
                }
            )
            return
        if self.path == "/api/embed":
            inputs = payload.get("input")
            if not isinstance(inputs, list) or not all(isinstance(text, str) for text in inputs):
                self._respond({"error": "invalid input"}, status=400)
                return
            self._respond({"embeddings": [_embedding(text) for text in inputs]})
            return
        if self.path == "/api/chat":
            self._respond(
                {
                    "done": True,
                    "message": {"role": "assistant", "content": '{"status":"ok"}'},
                }
            )
            return
        self._respond({"error": "not found"}, status=404)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 11434), OllamaStubHandler)
    server.serve_forever()


if __name__ == "__main__":
    main()
