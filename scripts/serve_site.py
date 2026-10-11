"""Run only a built public site on loopback; never expose the checkout or RAW."""

from __future__ import annotations

import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from scripts.build_site import build_site
except ModuleNotFoundError:
    from build_site import build_site


class PublicSiteHandler(SimpleHTTPRequestHandler):
    def list_directory(self, path: str) -> None:
        self.send_error(404)
        return None

    def log_message(self, format: str, *args: object) -> None:
        # Query strings must not become logs if a user pastes a sensitive URL.
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--snapshot", type=Path)
    args = parser.parse_args()
    with TemporaryDirectory(prefix="analisis-public-site-") as temporary:
        directory = Path(temporary) / "site"
        build_site(directory, snapshot=args.snapshot)
        handler = partial(PublicSiteHandler, directory=str(directory))
        with ThreadingHTTPServer(("127.0.0.1", args.port), handler) as server:
            print(f"Public HTML site running on local port {server.server_port}.", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
