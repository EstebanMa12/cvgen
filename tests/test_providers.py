import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from cvgen.config import ConfigError
from cvgen.providers.base import ProviderError, canonicalize
from cvgen.providers.compatible_provider import _chat_url
from cvgen.providers.compatible_provider import complete as compatible_complete
from cvgen.providers.cursor_provider import complete as cursor_complete
from cvgen.providers.openai_provider import complete as openai_complete


def test_provider_aliases():
    assert canonicalize("Google") == "gemini"
    assert canonicalize("local") == "ollama"
    assert canonicalize("openai_compatible") == "openai-compatible"
    with pytest.raises(ConfigError):
        canonicalize("not-a-provider")


def test_openai_extra_is_optional(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr("cvgen.providers.openai_provider.openai", None)
    with pytest.raises(ProviderError, match=r"cvgen\[openai\]"):
        openai_complete(
            model="gpt-4o-mini",
            base_url=None,
            temperature=0.2,
            api_key_env=None,
            system="system",
            user="user",
        )


def test_chat_url_accepts_a_host_or_a_v1_root():
    assert _chat_url("http://127.0.0.1:11434") == "http://127.0.0.1:11434/v1/chat/completions"
    assert _chat_url("http://127.0.0.1:11434/v1") == "http://127.0.0.1:11434/v1/chat/completions"


def test_compatible_provider_reads_chat_completions():
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(length))
            assert body["model"] == "test-model"
            assert body["messages"][0]["role"] == "system"
            payload = json.dumps({"choices": [{"message": {"content": "hello from model"}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        text = compatible_complete(
            model="test-model",
            base_url=f"http://127.0.0.1:{port}",
            temperature=0.2,
            api_key_env=None,
            system="rules",
            user="write a cv",
        )
    finally:
        server.shutdown()
    assert text == "hello from model"


def test_cursor_provider_explains_the_node_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("CURSOR_API_KEY", "test-key")
    monkeypatch.setenv("CVGEN_CURSOR_HOME", str(tmp_path))
    monkeypatch.setattr("cvgen.providers.cursor_provider.shutil.which", lambda _name: "/usr/bin/node")
    with pytest.raises(ProviderError, match="npm install"):
        cursor_complete(
            model="composer-2",
            api_key_env=None,
            system="system",
            user="user",
            cwd=tmp_path,
        )
    assert (tmp_path / "cursor_agent.mjs").is_file()
    assert (tmp_path / "package.json").is_file()
