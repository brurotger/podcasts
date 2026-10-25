"""App local da apuração: abre a página no seu computador, sem GitHub no meio.

Serve docs/eleicoes/ e repassa para o TSE tudo o que a página pede em /tse/...,
então não depende de CORS, de commits nem do cache do GitHub Pages.
Só usa a biblioteca padrão do Python 3.

Uso:
    python eleicoes/app_local.py            # abre http://localhost:8080
    python eleicoes/app_local.py --porta 9000 --sem-navegador
"""

import argparse
import functools
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

TSE = "https://resultados.tse.jus.br/oficial"
PAGINA = Path(__file__).resolve().parent.parent / "docs" / "eleicoes"
CACHE_S = 2  # vários pedidos iguais em 2s viram uma consulta só ao TSE
HEADERS = {"User-Agent": "Mozilla/5.0 (app local de apuracao)", "Accept": "application/json"}

_cache = {}
_lock = threading.Lock()


def buscar_tse(path):
    agora = time.time()
    with _lock:
        hit = _cache.get(path)
        if hit and agora - hit[0] < CACHE_S:
            return hit[1], hit[2]
    try:
        req = urllib.request.Request(TSE + path, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as r:
            status, corpo = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, corpo = e.code, b""
    with _lock:
        _cache[path] = (agora, status, corpo)
    return status, corpo


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if not self.path.startswith("/tse/"):
            return super().do_GET()
        path = self.path[len("/tse"):].split("?", 1)[0]
        try:
            status, corpo = buscar_tse(path)
        except Exception as e:  # noqa: BLE001
            self.send_error(502, f"TSE inacessível: {e}")
            return
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def end_headers(self):
        if not self.path.startswith("/tse/"):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        if args and str(args[1]) not in ("200", "304"):
            super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--porta", type=int, default=8080)
    ap.add_argument("--sem-navegador", action="store_true")
    a = ap.parse_args()

    srv = ThreadingHTTPServer(("127.0.0.1", a.porta), functools.partial(Handler, directory=str(PAGINA)))
    url = f"http://localhost:{a.porta}/"
    print(f"Apuração rodando em {url}  (Ctrl+C para sair)")
    if not a.sem_navegador:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
