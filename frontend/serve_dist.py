"""Static server + reverse proxy for the built frontend (mimics production nginx.conf).

Serves frontend/dist/ and proxies:
  /api/* -> http://127.0.0.1:8000/api/*
  /ws    -> ws://127.0.0.1:8000/ws   (raw byte tunnel after handshake)

This lets us run the *real built SPA* against the *real backend* for an
end-to-end UI smoke test without docker/nginx.
"""
import http.client
import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DIST = os.path.join(os.path.dirname(__file__), "dist")
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
LISTEN_PORT = 8080


def proxy_http(self):
    target = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=30)
    body = None
    if self.command in ("POST", "PUT", "PATCH"):
        length = int(self.headers.get("Content-Length", 0) or 0)
        body = self.rfile.read(length) if length else None
    headers = {k: v for k, v in self.headers.items() if k.lower() != "host"}
    target.request(self.command, self.path, body=body, headers=headers)
    resp = target.getresponse()
    self.send_response(resp.status)
    for k, v in resp.getheaders():
        if k.lower() == "transfer-encoding":
            continue
        self.send_header(k, v)
    self.end_headers()
    self.wfile.write(resp.read())
    target.close()


def tunnel_ws(self):
    # Connect to backend, forward the raw handshake, then byte-copy both ways.
    client = self.connection
    srv = socket.create_connection((BACKEND_HOST, BACKEND_PORT), timeout=10)
    srv.sendall(
        (f"{self.command} {self.path} HTTP/1.1\r\n").encode()
        + b"".join(
            f"{k}: {v}\r\n".encode() for k, v in self.headers.items() if k.lower() != "host"
        )
        + b"Host: 127.0.0.1:8000\r\n\r\n"
    )

    def pipe(src, dst):
        try:
            while True:
                data = src.recv(65536)
                if not data:
                    break
                dst.sendall(data)
        except Exception:
            pass

    t1 = threading.Thread(target=pipe, args=(srv, client), daemon=True)
    t2 = threading.Thread(target=pipe, args=(client, srv), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()


class Handler(BaseHTTPRequestHandler):
    def _serve_static(self):
        rel = self.path.split("?", 1)[0].split("#", 1)[0]
        if rel == "/" or rel == "":
            rel = "/index.html"
        # SPA: unknown paths with no extension fall back to index.html
        candidate = os.path.normpath(os.path.join(DIST, rel.lstrip("/")))
        if not candidate.startswith(DIST):
            self.send_error(403)
            return
        if not os.path.isfile(candidate):
            if "." not in os.path.basename(rel):
                candidate = os.path.join(DIST, "index.html")
            else:
                self.send_error(404)
                return
        with open(candidate, "rb") as f:
            data = f.read()
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".json": "application/json",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".ico": "image/x-icon",
        }.get(os.path.splitext(candidate)[1], "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/"):
            return proxy_http(self)
        if self.path == "/ws" or self.path.startswith("/ws?"):
            return tunnel_ws(self)
        return self._serve_static()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return proxy_http(self)
        self.send_error(405)

    def do_PUT(self):
        if self.path.startswith("/api/"):
            return proxy_http(self)
        self.send_error(405)

    def do_DELETE(self):
        if self.path.startswith("/api/"):
            return proxy_http(self)
        self.send_error(405)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    os.makedirs(DIST, exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", LISTEN_PORT), Handler)
    print(f"Serving {DIST} on http://127.0.0.1:{LISTEN_PORT} (proxy -> :{BACKEND_PORT})")
    srv.serve_forever()
