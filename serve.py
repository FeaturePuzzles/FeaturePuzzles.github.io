#!/usr/bin/env python
"""Static server for the project page, with byte-range support.

``python -m http.server`` answers every request with the whole file, which for a
36 MB follow-camera render means the browser cannot seek until the download
finishes and cannot start playing early. Chrome and Safari also refuse to treat
a video as seekable at all without ``Accept-Ranges``. This handler adds the one
missing piece and otherwise behaves exactly like the stock one.

    ./serve.sh            # http://localhost:8800
    python serve.py 9001
"""
from __future__ import annotations

import os
import re
import sys
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")
CHUNK = 256 * 1024


class RangeHandler(SimpleHTTPRequestHandler):
    """SimpleHTTPRequestHandler + RFC 7233 single-range responses."""

    protocol_version = "HTTP/1.1"

    def send_head(self):  # noqa: C901 - mirrors the stdlib method it replaces
        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()

        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()

        m = RANGE_RE.match(rng.strip())
        if not m:
            return super().send_head()

        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None

        try:
            size = os.fstat(f.fileno()).st_size
            first, last = m.group(1), m.group(2)
            if first == "":                       # bytes=-N  -> the final N bytes
                if last == "":
                    raise ValueError("empty range")
                start, end = max(0, size - int(last)), size - 1
            else:
                start = int(first)
                end = int(last) if last else size - 1
            end = min(end, size - 1)
            if start > end or start >= size:
                f.close()
                self.send_response(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                self.send_header("Content-Range", f"bytes */{size}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
        except ValueError:
            f.close()
            return super().send_head()

        f.seek(start)
        self._remaining = end - start + 1
        self.send_response(HTTPStatus.PARTIAL_CONTENT)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(self._remaining))
        self.send_header("Last-Modified", self.date_time_string(os.fstat(f.fileno()).st_mtime))
        self.end_headers()
        return f

    def copyfile(self, source, outputfile):
        """Copy only the requested slice when this was a range response."""
        remaining = getattr(self, "_remaining", None)
        if remaining is None:
            return super().copyfile(source, outputfile)
        self._remaining = None
        while remaining > 0:
            buf = source.read(min(CHUNK, remaining))
            if not buf:
                break
            outputfile.write(buf)
            remaining -= len(buf)

    def end_headers(self):
        # A plain 200 must advertise ranges too, or the browser never asks.
        if "Accept-Ranges" not in self._headers_buffer_names():
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def _headers_buffer_names(self) -> set[str]:
        out = set()
        for raw in getattr(self, "_headers_buffer", []):
            line = raw.decode("latin-1", "replace")
            if ":" in line:
                out.add(line.split(":", 1)[0].strip())
        return out

    def log_message(self, fmt, *args):
        if "404" in (args[1] if len(args) > 1 else ""):
            super().log_message(fmt, *args)


def main() -> int:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8800
    root = Path(__file__).resolve().parent
    handler = partial(RangeHandler, directory=str(root))
    srv = ThreadingHTTPServer(("0.0.0.0", port), handler)
    print(f"Feature Puzzles project page -> http://localhost:{port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
