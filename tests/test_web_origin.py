import http.client
import threading

from review.demo import DEFAULT, load
from review.web import create_server

PUBLIC = "https://review.example.ts.net:8765"


def request(server, method, host, origin=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_port)
    headers = {"Host": host}
    if origin:
        headers["Origin"] = origin
    body = "csrf=wrong" if method == "POST" else None
    if body:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    conn.request(method, "/" if method == "GET" else "/decision", body=body, headers=headers)
    status = conn.getresponse().status
    conn.close()
    return status


def test_public_origin_is_the_only_extra_trusted_host(tmp_path):
    store, _ = load(DEFAULT, local=tmp_path / "demo", runs=tmp_path / "runs")
    server = create_server(store, port=0, trace_dir=tmp_path / "runs", public_origin=PUBLIC)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert request(server, "GET", "review.example.ts.net:8765") == 200
        assert request(server, "GET", f"127.0.0.1:{server.server_port}") == 200
        assert request(server, "GET", "evil.example") == 403
        # trusted host + foreign origin is refused before CSRF is even checked
        assert request(server, "POST", "review.example.ts.net:8765", "https://evil.example") == 403
        # trusted origin reaches the CSRF check, which rejects a bad token
        assert request(server, "POST", "review.example.ts.net:8765", PUBLIC) == 403
    finally:
        server.shutdown()
        server.server_close()
