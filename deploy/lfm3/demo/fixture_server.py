#!/usr/bin/env python3
"""Deterministic, simulated OpenAI-compatible fixture for the local web demo.

NEVER authentic LFM3 inference, no model weights, no private secrets.
"""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODEL = "lfm3-1.7b-demo-fixture"
LABEL = "[SIMULATED DEMO RESPONSE — NOT REAL MODEL INFERENCE]"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass  # do not put demo prompts or headers into container logs

    def respond(self, status, body):
        data = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/v1/models":
            return self.respond(200, {"data": [{"id": MODEL}]})
        return self.respond(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            return self.respond(404, {"error": "not found"})
        try:
            size = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            size = 0
        if size < 1 or size > 8192:
            return self.respond(413, {"error": "fixture input is too large"})
        try:
            payload = json.loads(self.rfile.read(size))
        except (ValueError, UnicodeDecodeError):
            return self.respond(400, {"error": "malformed fixture input"})
        if (not isinstance(payload, dict) or payload.get("model") != MODEL or
                not isinstance(payload.get("messages"), list) or
                self.headers.get("Authorization") or payload.get("tools")):
            return self.respond(400, {"error": "unsupported fixture call"})
        messages = payload["messages"]
        if not messages or not isinstance(messages[-1], dict):
            return self.respond(400, {"error": "missing user turn"})
        prompt = messages[-1].get("content")
        if not isinstance(prompt, str) or not prompt.strip():
            return self.respond(400, {"error": "invalid prompt"})
        if "2 + 2" in prompt or "2+2" in prompt:
            answer = "4 " + LABEL
        else:
            answer = LABEL + " Your message was received: " + prompt.strip()[:180]
        return self.respond(200, {
            "model": MODEL,
            "choices": [{"message": {"role": "assistant", "content": answer}}],
        })


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8077), Handler).serve_forever()
