"""Loopback-only synthetic review UI. No network delivery implementation exists."""

import argparse
import json
import re
import secrets
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ledgerline_crm.store import Store

STYLE = """
body{margin:0;background:#f3f2ec;color:#203132;font:16px/1.5 system-ui,sans-serif}
main{max-width:1080px;margin:40px auto;padding:0 24px}h1{font-size:32px;margin-bottom:0}
header{border-bottom:3px solid #36776b;padding-bottom:20px}small{color:#536765}
article{background:white;border:1px solid #c7d2ca;border-radius:8px;padding:26px;margin:24px 0}
.badge{color:#775010;background:#fff0c9;padding:4px 10px;border-radius:20px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f5f7f5;padding:14px;font-size:13px}
textarea{width:100%;box-sizing:border-box;min-height:440px;font:inherit;padding:12px}
label{display:block;font-weight:600;margin-top:12px}input{font:inherit;padding:8px;max-width:90%}
button{background:#225d50;color:white;padding:12px 18px;border:0;border-radius:4px;margin:16px 8px 0 0;font:inherit;cursor:pointer}
button[value=reject]{background:#7c3633}.columns{display:grid;grid-template-columns:1fr 1fr;gap:24px}
@media(max-width:700px){.columns{display:block}main{padding:0 12px}}
"""


def page(store, csrf, trace_dir):
    items = []
    for p in reversed(store.proposals()):
        if p["status"] != "pending":
            continue
        lead = store.rows("SELECT * FROM leads WHERE id=?", (p["lead_id"],))[0]
        trail = []
        if re.fullmatch(r"[a-zA-Z0-9_-]+", p["run_id"]):
            trace = Path(trace_dir) / (p["run_id"] + ".jsonl")
            if trace.exists():
                trail = [
                    json.loads(line)
                    for line in trace.read_text().splitlines()
                    if json.loads(line).get("type") == "tool"
                ]
        research = escape(json.dumps(trail, indent=2, ensure_ascii=False))
        items.append(f"""<article><span class="badge">pending</span>
        <h2>{escape(lead["company"])} <small>#{p["id"]} · {escape(p["route"])} · {escape(p["priority"])}</small></h2>
        <p>{escape(lead["name"])} &lt;{escape(lead["email"])}&gt; · {escape(lead["channel"])}</p>
        <div class="columns"><section><h3>Inbound lead · untrusted</h3><pre>{escape(lead["message"])}</pre>
        <h3>Rationale</h3><p>{escape(p["rationale"])}</p>
        <h3>KB citations</h3><p>{escape(", ".join(p["citations"])) or "None"}</p></section>
        <section><form method="post" action="/decision">
        <input type="hidden" name="csrf" value="{csrf}">
        <input type="hidden" name="proposal_id" value="{p["id"]}">
        <label for="draft-{p["id"]}">Draft reply · nothing has been sent</label>
        <textarea id="draft-{p["id"]}" name="draft_reply">{escape(p["draft_reply"])}</textarea>
        <label>Reviewer <input name="who" required placeholder="Your name"></label>
        <label>Reason <input name="reason" placeholder="Required for rejection"></label>
        <button name="action" value="approve">Approve original</button>
        <button name="action" value="edit_approve">Edit + approve</button>
        <button name="action" value="reject">Reject</button>
        </form></section></div>
        <details><summary>Research trail · {len(trail)} tool calls · {escape(p["run_id"])}</summary><pre>{research}</pre></details>
        </article>""")
    return (
        f'<!doctype html><html lang="en"><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>Ledgerline · Human review</title><style>{STYLE}</style><main>"
        "<header><small>LEDGERLINE / SYNTHETIC SANDBOX</small><h1>Human review queue</h1>"
        "<p>Proposed actions, not sent messages. Approval writes to a simulated outbox only.</p></header>"
        + ("".join(items) or "<p>No pending proposals.</p>")
        + "</main></html>"
    )


def create_server(store, port=8765, trace_dir=Path("runs"), public_origin=None):
    """Bind to loopback only. public_origin (e.g. a tailnet HTTPS URL fronted by a
    reverse proxy) is the one extra Host/Origin the UI will accept."""

    class Handler(BaseHTTPRequestHandler):
        def origins(self):
            allowed = {f"http://127.0.0.1:{self.server.server_port}"}
            if public_origin:
                allowed.add(public_origin.rstrip("/"))
            return allowed

        def trusted(self):
            hosts = {urlsplit(o).netloc for o in self.origins()}
            return self.headers.get("Host") in hosts

        def reply(self, status, body):
            payload = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'",
            )
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self):
            if not self.trusted():
                return self.reply(403, "Invalid Host")
            if self.path != "/":
                return self.reply(404, "Not found")
            self.reply(200, page(store, self.server.csrf, trace_dir))

        def do_POST(self):
            origin = self.headers.get("Origin")
            if not self.trusted() or (origin is not None and origin not in self.origins()):
                return self.reply(403, "Invalid origin")
            if self.path != "/decision":
                return self.reply(404, "Not found")
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length < 1 or length > 32000:
                    return self.reply(413, "Invalid body length")
                form = parse_qs(self.rfile.read(length).decode(), keep_blank_values=True)

                def value(key):
                    return form.get(key, [""])[0]

                if not secrets.compare_digest(value("csrf"), self.server.csrf):
                    return self.reply(403, "Invalid CSRF token")
                store.review(
                    int(value("proposal_id")),
                    value("action"),
                    value("who"),
                    value("draft_reply"),
                    value("reason"),
                )
            except (ValueError, UnicodeError) as exc:
                return self.reply(400, escape(str(exc)))
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Content-Length", "0")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.csrf = secrets.token_urlsafe(32)
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", default="local/crm.db")
    parser.add_argument("--audit", default="local/audit.jsonl")
    parser.add_argument(
        "--public-origin",
        help="extra trusted origin when fronted by a reverse proxy, e.g. https://host.tailnet.ts.net:8765",
    )
    args = parser.parse_args()
    server = create_server(Store(args.db, args.audit), args.port, public_origin=args.public_origin)
    print(f"Review UI: http://127.0.0.1:{server.server_port} (simulated outbox only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
