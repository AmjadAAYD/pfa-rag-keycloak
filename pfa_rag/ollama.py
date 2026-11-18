"""Local Ollama transport and model identity."""

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class OllamaModel:
    def __init__(self, url: str, model: str):
        self.url = url.rstrip("/")
        self.model = model if ":" in model.rsplit("/", 1)[-1] else f"{model}:latest"

    def model_digest(self) -> str:
        models = self._request("/api/tags", timeout=5).get("models")
        if not isinstance(models, list):
            raise ValueError("Ollama returned an invalid model list")
        for record in models:
            if isinstance(record, dict) and record.get("name") == self.model:
                digest = record.get("digest")
                if isinstance(digest, str) and digest:
                    return digest
                raise ValueError(f"Ollama returned no digest for {self.model}")
        raise ValueError(f"Ollama model {self.model} is missing. Run ollama pull {self.model}")

    def _request(self, path: str, data: dict | None = None, *, timeout: int = 180) -> dict:
        body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
        request = Request(self.url + path, data=body, headers={"Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=timeout) as response:
                payload = json.load(response)
        except HTTPError as error:
            with error:
                detail = error.read(1024).decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Ollama {path} returned HTTP {error.code}: {detail}") from error
        except (URLError, TimeoutError) as error:
            raise RuntimeError(f"Could not reach Ollama at {self.url}: {error}") from error
        if not isinstance(payload, dict):
            raise ValueError(f"Ollama returned an invalid response for {path}")
        return payload
