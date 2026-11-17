"""Local no-cost mock OpenAI-compatible model for checking the interface.

Run: python scripts/mock_provider.py
Configure base URL: http://127.0.0.1:8765/v1
Model ID: mock-text-model (no key)
"""
from __future__ import annotations
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import time


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/v1/models":
            self.send_error(404)
            return
        self.send_json({"object": "list", "data": [{"id": "mock-text-model", "object": "model"}]})

    def send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 1024 * 1024:
                self.send_json({"error": "too large"}, 413)
                return
            body = json.loads(self.rfile.read(length))
            text = body.get("messages", [{}])[-1].get("content", "")
            match = re.search(r"<(source_text_[0-9a-f]+)>\n(.*)\n</\1>", text, re.S)
            source = match.group(2) if match else text
            preview = "[MOCK RESPONSE — no AI was used] " + source[:2000]
            if body.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                if "think" in str(body.get("model", "")):
                    # Like a reasoning model on Ollama: thinking arrives first, with no content.
                    for word in ("Let", " me", " think", " about", " this", "..."):
                        chunk = json.dumps({"choices": [{"delta": {"content": "", "reasoning": word}}]})
                        self.wfile.write(("data: " + chunk + "\n\n").encode("utf-8"))
                        self.wfile.flush()
                        time.sleep(0.25)
                for word in preview.split(" "):
                    chunk = json.dumps({"choices": [{"delta": {"content": word + " "}}]})
                    self.wfile.write(("data: " + chunk + "\n\n").encode("utf-8"))
                    self.wfile.flush()
                    time.sleep(0.04)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
            else:
                self.send_json({"choices": [{"message": {"role": "assistant", "content": preview}}]})
        except (OSError, ValueError, json.JSONDecodeError):
            try:
                self.send_json({"error": "Invalid request"}, 400)
            except OSError:
                pass

    def log_message(self, fmt, *args):
        # Do not log raw request payloads; only request metadata.
        print("[mock]", fmt % args)


if __name__ == "__main__":
    print("Mock API on http://127.0.0.1:8765/v1 - model: mock-text-model")
    ThreadingHTTPServer(("127.0.0.1", 8765), Handler).serve_forever()
