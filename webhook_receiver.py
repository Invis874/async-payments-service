"""Локальный приёмник вебхуков.
Запуск: python webhook_receiver.py
Слушает http://0.0.0.0:9999/webhook
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import json


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        print("=" * 60)
        print(f"POST {self.path}")
        for k, v in self.headers.items():
            print(f"  {k}: {v}")
        print("-" * 60)
        try:
            print(json.dumps(json.loads(body), indent=2, ensure_ascii=False))
        except Exception:
            print(body.decode(errors="replace"))
        print("=" * 60)

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print("Listening on http://0.0.0.0:9999/webhook")
    HTTPServer(("0.0.0.0", 9999), Handler).serve_forever()