"""Opt-in HTTP boundary; reuse the frozen Gate ledger and forwarding semantics.

The server exclusively owns calls to its Gate. No retry, refund, or launcher
default change. Error responses contain codes, never provider exception text.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import urllib.error


def serve(gate):
    request_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def respond(self, status, code):
            raw = json.dumps({"error": {"code": code,
                "message": "Request not completed; inspect operator ledger."}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            if self.path != '/v1/chat/completions' or self.headers.get('Authorization') != 'Bearer ' + gate.token:
                self.respond(403, 'access_denied')
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 4_000_000:
                    raise ValueError('size')
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict) or body.get('model') != gate.model:
                    raise ValueError('model')
                requested = body.get('max_completion_tokens', body.get('max_tokens', gate.output))
                if type(requested) is not int or requested < 1:
                    raise ValueError('output bound')
            except (ValueError, UnicodeError):
                self.respond(400, 'invalid_request')
                return
            if not request_lock.acquire(blocking=False):
                self.respond(409, 'request_in_flight')
                return
            try:
                if gate.closed:
                    self.respond(409, 'gate_closed')
                    return
                if len(gate.events) >= gate.limit:
                    self.respond(409, 'request_budget_exhausted')
                    return
                try:
                    raw = gate.call(body)
                except urllib.error.HTTPError as error:
                    status = error.code if 400 <= error.code <= 599 else 502
                    self.respond(status, 'upstream_http_error')
                    return
                except (TimeoutError, urllib.error.URLError) as error:
                    timed_out = isinstance(error, TimeoutError) or isinstance(getattr(error, 'reason', None), TimeoutError)
                    self.respond(504 if timed_out else 502, 'upstream_timeout' if timed_out else 'upstream_transport_error')
                    return
                except MemoryError:
                    self.respond(500, 'host_memory_error')
                    return
                except Exception:
                    self.respond(502, 'request_processing_failed')
                    return
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
            finally:
                request_lock.release()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
