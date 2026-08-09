"""Minimal HTTP/HTTPS client for MicroPython.

urequests does not reliably handle chunked transfer-encoding, which the OpenAI
API uses for non-streamed responses, so the agent ships its own client. It
supports Content-Length bodies, chunked bodies, read-until-close, and optional
certificate verification against a DER-encoded root CA.
"""

import json as _json
import socket
import ssl as _ssl


class HTTPError(Exception):
    pass


class Response:
    def __init__(self, status, headers, content):
        self.status_code = status
        self.headers = headers
        self.content = content

    @property
    def text(self):
        return self.content.decode("utf-8")

    def json(self):
        return _json.loads(self.content)

    def __repr__(self):
        return "<Response %d, %d bytes>" % (self.status_code, len(self.content))


def parse_url(url):
    try:
        scheme, rest = url.split("://", 1)
    except ValueError:
        raise HTTPError("malformed URL: %s" % url)
    scheme = scheme.lower()
    if "/" in rest:
        hostport, path = rest.split("/", 1)
        path = "/" + path
    else:
        hostport, path = rest, "/"
    if ":" in hostport:
        host, port_s = hostport.rsplit(":", 1)
        port = int(port_s)
    else:
        host = hostport
        port = 443 if scheme == "https" else 80
    return scheme, host, port, path


def _wrap_tls(sock, host, cadata):
    # SSLContext is the modern API; fall back for older builds.
    try:
        ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_CLIENT)
    except AttributeError:
        return _ssl.wrap_socket(sock, server_hostname=host)
    if cadata:
        ctx.verify_mode = _ssl.CERT_REQUIRED
        ctx.load_verify_locations(cadata=cadata)
    else:
        ctx.verify_mode = _ssl.CERT_NONE
    return ctx.wrap_socket(sock, server_hostname=host)


def _read_headers(sock):
    line = sock.readline()
    if not line:
        raise HTTPError("empty response from server")
    parts = line.split(None, 2)
    if len(parts) < 2:
        raise HTTPError("bad status line: %r" % line)
    status = int(parts[1])
    headers = {}
    while True:
        line = sock.readline()
        if not line or line in (b"\r\n", b"\n"):
            break
        if b":" in line:
            k, v = line.split(b":", 1)
            headers[k.decode().strip().lower()] = v.decode().strip()
    return status, headers


def _read_exactly(sock, n):
    parts = []
    got = 0
    while got < n:
        chunk = sock.read(min(2048, n - got))
        if not chunk:
            break
        parts.append(chunk)
        got += len(chunk)
    return b"".join(parts)


def _read_body(sock, headers, max_bytes):
    encoding = headers.get("transfer-encoding", "")
    if "chunked" in encoding:
        parts = []
        total = 0
        while True:
            line = sock.readline()
            if not line:
                break
            line = line.strip()
            if b";" in line:
                line = line.split(b";", 1)[0]
            if not line:
                continue
            try:
                size = int(line, 16)
            except ValueError:
                break
            if size == 0:
                break
            chunk = _read_exactly(sock, size)
            sock.readline()  # trailing CRLF
            total += len(chunk)
            if max_bytes and total > max_bytes:
                parts.append(chunk[: max_bytes - (total - len(chunk))])
                break
            parts.append(chunk)
        return b"".join(parts)

    if "content-length" in headers:
        length = int(headers["content-length"])
        if max_bytes:
            length = min(length, max_bytes)
        return _read_exactly(sock, length)

    parts = []
    total = 0
    while True:
        chunk = sock.read(2048)
        if not chunk:
            break
        parts.append(chunk)
        total += len(chunk)
        if max_bytes and total >= max_bytes:
            break
    return b"".join(parts)


def request(method, url, headers=None, body=None, timeout=45, cadata=None,
            max_bytes=0):
    scheme, host, port, path = parse_url(url)
    hdrs = dict(headers or {})

    if isinstance(body, (dict, list)):
        body = _json.dumps(body)
        hdrs.setdefault("Content-Type", "application/json")
    if isinstance(body, str):
        body = body.encode("utf-8")

    addr = socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)[0]
    sock = socket.socket(addr[0], addr[1], addr[2])
    sock.settimeout(timeout)
    try:
        sock.connect(addr[-1])
        if scheme == "https":
            sock = _wrap_tls(sock, host, cadata)

        hdrs.setdefault("Host", host)
        hdrs.setdefault("Accept", "*/*")
        hdrs.setdefault("User-Agent", "esp32s3-agent/1.0")
        hdrs.setdefault("Connection", "close")
        if body is not None:
            hdrs["Content-Length"] = str(len(body))

        req = bytearray()
        req += b"%s %s HTTP/1.1\r\n" % (method.encode(), path.encode())
        for key, value in hdrs.items():
            req += b"%s: %s\r\n" % (key.encode(), str(value).encode())
        req += b"\r\n"
        sock.write(bytes(req))

        if body:
            view = memoryview(body)
            for i in range(0, len(view), 1024):
                sock.write(view[i:i + 1024])

        status, resp_headers = _read_headers(sock)
        content = _read_body(sock, resp_headers, max_bytes)
        return Response(status, resp_headers, content)
    finally:
        try:
            sock.close()
        except Exception:
            pass


def get(url, **kw):
    return request("GET", url, **kw)


def post(url, **kw):
    return request("POST", url, **kw)


def load_ca(path):
    """Read a DER-encoded root certificate, returning None when unavailable."""
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        print("[http] CA cert %s not found; TLS verification disabled" % path)
        return None
