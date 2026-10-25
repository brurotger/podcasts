"""Copia os resultados do TSE (2º turno presidencial) para docs/eleicoes/dados/.

A página de apuração lê o TSE direto do navegador; quando isso falha, ela usa
esta cópia, servida pelo GitHub Pages no mesmo endereço do site.

Arquivos gerados (mesmos caminhos do TSE, abaixo de dados/):
  atual.json                                   eleição em uso, formato e horário da cópia
  ele<ano>/<cd>/dados/br/br-c0001-e<cd6>-u.json  nacional e um por estado
  ele<ano>/<cd>/config/mun-e<cd6>-cm.json        cadastro de municípios
  mun/<uf>.json                                  resultados das cidades do estado, compactados

Uso: python espelho_tse.py <pasta de saída> [--loop-minutos N] [--git]
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = "https://resultados.tse.jus.br/oficial"
ANO = os.environ.get("ANO", "2026")
CODIGOS_T2 = {"2026": "6258", "2022": "545"}
UFS = ["ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt", "pa", "pb",
       "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to"]
HEADERS = {"User-Agent": "Mozilla/5.0 (espelho de apuracao; github.com/brurotger/podcasts)",
           "Accept": "application/json"}


def log(*a):
    print(dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


class Http404(Exception):
    pass


def baixar(path):
    req = urllib.request.Request(BASE + path, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code in (403, 404):
            raise Http404(f"{e.code} {path}") from e
        raise


def salvar(out, path, data):
    """Grava só se mudou. Devolve True quando o arquivo mudou."""
    dest = os.path.join(out, path.lstrip("/"))
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        with open(dest, "rb") as f:
            if f.read() == data:
                return False
    # grava num temporário e troca de uma vez, para o git nunca pegar um arquivo pela metade
    tmp = dest + ".tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, dest)
    return True


def descobrir():
    if os.environ.get("ELEICAO"):
        return {"cd": os.environ["ELEICAO"], "cd1": None}
    try:
        cfg = json.loads(baixar("/comum/config/ele-c.json"))
    except Exception as e:  # noqa: BLE001
        log("ele-c.json falhou:", e)
        return {"cd": CODIGOS_T2[ANO], "cd1": None}
    links, t2 = [], []

    def walk(o, d):
        if isinstance(o, list):
            for x in o:
                walk(x, d)
            return
        if not isinstance(o, dict):
            return
        d = str(o.get("dt") or d or "")
        if o.get("cd") is not None and o.get("cdt2") is not None and ANO in d:
            links.append({"cd1": str(o["cd"]), "cd": str(o["cdt2"]), "nm": o.get("nm", "")})
        if o.get("cd") is not None and str(o.get("t")) == "2" and not isinstance(o.get("e"), list) and ANO in d:
            t2.append({"cd": str(o["cd"]), "nm": o.get("nm", "")})
        for v in o.values():
            if isinstance(v, (dict, list)):
                walk(v, d)

    walk(cfg, "")
    log("ele-c.json: ligações 1º→2º turno", links, "| entradas de 2º turno", t2)
    if links:
        return {"cd": links[0]["cd"], "cd1": links[0]["cd1"]}
    if t2:
        return {"cd": t2[0]["cd"], "cd1": None}
    return {"cd": CODIGOS_T2[ANO], "cd1": None}


def caminho(ele, fmt, nivel):
    e = "e" + ele["cd"].zfill(6)
    if fmt == "r":
        return f"/ele{ANO}/{ele['cd']}/dados-simplificados/{nivel}-c0001-{e}-r.json"
    return f"/ele{ANO}/{ele['cd']}/dados/{nivel}-c0001-{e}-u.json"


def candidatos(j):
    if isinstance(j.get("cand"), list):
        return j["cand"]
    out, vistos = [], set()

    def walk(o, sg):
        if isinstance(o, list):
            for x in o:
                walk(x, sg)
            return
        if not isinstance(o, dict):
            return
        sg = o.get("sg") or sg
        for c in o.get("cand") or []:
            if str(c.get("n")) not in vistos:
                vistos.add(str(c.get("n")))
                out.append({**c, "sg": sg})
        for k, v in o.items():
            if k != "cand" and isinstance(v, (dict, list)):
                walk(v, sg)

    walk(j.get("carg") or [], None)
    return out


def compactar(j):
    """Só o que a página usa de cada cidade."""
    keep = ("s", "st", "pst", "e", "c", "pc", "a", "pa", "vb", "pvb", "tvn", "vn", "ptvn", "pvn", "dg", "hg", "dt", "ht")
    r = {k: j[k] for k in keep if k in j}
    r["cand"] = [{k: c[k] for k in ("n", "nm", "nmu", "sg", "cc", "vap", "pvap", "e", "st") if k in c} for c in candidatos(j)]
    return r


def ciclo_nacional(out, ele, fmt):
    mudou = 0
    br = baixar(caminho(ele, fmt, "br/br"))
    mudou += salvar(out, caminho(ele, fmt, "br/br"), br)

    def uf(u):
        try:
            return u, baixar(caminho(ele, fmt, f"{u}/{u}"))
        except Exception as e:  # noqa: BLE001
            log("estado", u, "falhou:", e)
            return u, None

    with cf.ThreadPoolExecutor(8) as ex:
        for u, data in ex.map(uf, UFS):
            if data:
                mudou += salvar(out, caminho(ele, fmt, f"{u}/{u}"), data)
    j = json.loads(br)
    s = j.get("s") if isinstance(j.get("s"), dict) else j
    log(f"nacional: {s.get('pst')}% das seções; candidatos:",
        [(c.get("nmu") or c.get("nm"), c.get("pvap")) for c in candidatos(j)])
    return mudou


def cadastro_municipios(out, ele):
    for cd in [ele["cd"], ele.get("cd1") or str(int(ele["cd"]) - 1)]:
        path = f"/ele{ANO}/{cd}/config/mun-e{cd.zfill(6)}-cm.json"
        try:
            data = baixar(path)
        except Exception as e:  # noqa: BLE001
            log("cadastro de municípios", path, "falhou:", e)
            continue
        # a página procura o cadastro no caminho da eleição em uso
        salvar(out, f"/ele{ANO}/{ele['cd']}/config/mun-e{ele['cd'].zfill(6)}-cm.json", data)
        lista = {}

        def walk(o):
            if isinstance(o, list):
                for x in o:
                    walk(x)
                return
            if not isinstance(o, dict):
                return
            if isinstance(o.get("mu"), list):
                uf = str(o.get("cd") or "").lower()
                lista.setdefault(uf, []).extend(str(m["cd"]).zfill(5) for m in o["mu"])
                return
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v)

        walk(json.loads(data))
        return {uf: ms for uf, ms in lista.items() if uf in UFS}
    return {}


def ciclo_municipios(out, ele, fmt, cadastro):
    mudou = 0
    for uf in UFS:
        ms = cadastro.get(uf, [])
        res, faltando = {}, 0

        def um(m):
            try:
                return m, json.loads(baixar(caminho(ele, fmt, f"{uf}/{uf}{m}")))
            except Http404:
                return m, 404
            except Exception as e:  # noqa: BLE001
                log("cidade", uf, m, "falhou:", e)
                return m, None

        # testa poucas antes: muitos 404 seguidos fazem o TSE bloquear o IP
        amostra = ms[:5]
        with cf.ThreadPoolExecutor(5) as ex:
            for m, j in ex.map(um, amostra):
                if j == 404:
                    faltando += 1
                elif j:
                    res[m] = compactar(j)
        if faltando == len(amostra):
            log(f"{uf}: cidades ainda não publicadas")
            continue
        with cf.ThreadPoolExecutor(16) as ex:
            for m, j in ex.map(um, ms[5:]):
                if isinstance(j, dict):
                    res[m] = compactar(j)
        data = json.dumps({"gerado": agora(), "mu": res}, ensure_ascii=False, separators=(",", ":")).encode()
        mudou += salvar(out, f"/mun/{uf.upper()}.json", data)
        log(f"{uf}: {len(res)}/{len(ms)} cidades")
    return mudou


def agora():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=-3))).strftime("%d/%m/%Y %H:%M:%S")


def git_push(msg):
    subprocess.run(["git", "add", "-A", "--", "docs/eleicoes/dados", ":!*.tmp"], check=True)
    if subprocess.run(["git", "diff", "--cached", "--quiet"]).returncode == 0:
        return
    subprocess.run(["git", "commit", "-q", "-m", msg], check=True)
    for _ in range(4):
        subprocess.run(["git", "pull", "-q", "--rebase", "-X", "theirs", "origin", "main"])
        if subprocess.run(["git", "push", "-q", "origin", "HEAD:main"]).returncode == 0:
            log("publicado:", msg)
            return
        time.sleep(3)
    log("push falhou")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--loop-minutos", type=float, default=0)
    ap.add_argument("--intervalo", type=int, default=15, help="segundos entre consultas ao placar nacional")
    ap.add_argument("--commit-a-cada", type=int, default=60,
                    help="intervalo mínimo entre commits; menos que ~60s faz o GitHub Pages cancelar as publicações")
    ap.add_argument("--git", action="store_true")
    a = ap.parse_args()

    fim = time.time() + a.loop_minutos * 60
    ele, fmt = None, None
    while not fmt:
        try:
            ele = ele or descobrir()
            log("eleição em uso:", ele)
            for f in ("u", "r"):
                try:
                    baixar(caminho(ele, f, "br/br"))
                    fmt = f
                    break
                except Http404 as e:
                    log("formato", f, "indisponível:", e)
        except Exception as e:  # noqa: BLE001
            log("descoberta falhou:", repr(e))
        if not fmt:
            if time.time() >= fim:
                return 1
            time.sleep(30)

    # cidades numa linha separada: uma volta leva alguns minutos e não pode travar o placar
    def cidades():
        cadastro = None
        while time.time() < fim:
            inicio = time.time()
            try:
                cadastro = cadastro or cadastro_municipios(a.out, ele)
                if cadastro:
                    ciclo_municipios(a.out, ele, fmt, cadastro)
            except Exception as e:  # noqa: BLE001
                log("cidades falharam:", repr(e))
            time.sleep(max(30, 120 - (time.time() - inicio)))

    threading.Thread(target=cidades, daemon=True).start()

    ultimo_commit = 0
    while True:
        inicio = time.time()
        try:
            ciclo_nacional(a.out, ele, fmt)
            salvar(a.out, "/atual.json", json.dumps({"ano": ANO, "cd": ele["cd"], "cd1": ele.get("cd1"), "fmt": fmt, "gerado": agora()}).encode())
            if a.git and time.time() - ultimo_commit >= a.commit_a_cada:
                git_push(f"Apuração: dados do TSE às {agora()}")
                ultimo_commit = time.time()
        except Exception as e:  # noqa: BLE001
            log("ciclo falhou:", repr(e))
        if time.time() >= fim:
            break
        time.sleep(max(3, a.intervalo - (time.time() - inicio)))


if __name__ == "__main__":
    sys.exit(main())
