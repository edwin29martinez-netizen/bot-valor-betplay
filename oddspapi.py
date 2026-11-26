"""Cliente de la API oficial de OddsPapi v4 con caché para ahorrar consultas."""
from __future__ import annotations

import json
import os
import time
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import config

BASE = "https://api.oddspapi.io/v4"
CACHE = Path(__file__).parent / "data" / "cache.json"
consultas = 0
_ultima = 0.0


def norm(t) -> str:
    t = unicodedata.normalize("NFKD", str(t).lower())
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


def get(ruta: str, **params):
    """Una consulta, respetando la pausa de 1 s y reintentando si hay límite (429)."""
    global consultas, _ultima
    params["apiKey"] = os.environ["ODDSPAPI_KEY"].strip()
    for _ in range(4):
        espera = 1.1 - (time.time() - _ultima)
        if espera > 0:
            time.sleep(espera)
        consultas += 1
        _ultima = time.time()
        r = requests.get(f"{BASE}/{ruta}", params=params, timeout=60)
        if r.status_code == 429:
            try:
                ms = r.json().get("error", {}).get("retryMs", 2000)
            except Exception:
                ms = 2000
            time.sleep(min(ms, 10000) / 1000)
            continue
        if r.status_code == 404:
            return None
        if r.status_code >= 400:
            print(f"OddsPapi {ruta}: HTTP {r.status_code} {r.text[:300]}")
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"OddsPapi: demasiados reintentos en {ruta}")


def lista(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def _campo(d: dict, *nombres, defecto=None):
    for n in nombres:
        if isinstance(d, dict) and d.get(n) not in (None, ""):
            return d[n]
    return defecto


# ------------------------------------------------------------------ caché
def cargar_cache() -> dict:
    if CACHE.exists():
        try:
            return json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def guardar_cache(c: dict) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def cache_vencido(c: dict, dias: int = 7) -> bool:
    try:
        f = datetime.fromisoformat(c["actualizado"])
        return datetime.now(timezone.utc) - f > timedelta(days=dias)
    except Exception:
        return True


def refrescar_catalogo(c: dict, avisos: list[str]) -> None:
    """Deportes, torneos y mercados. ~5 consultas, una vez por semana."""
    deportes = {}
    for s in lista(get("sports")):
        nombre = norm(_campo(s, "slug", "sportName", "name", defecto=""))
        sid = _campo(s, "sportId", "id")
        if sid is not None:
            deportes[nombre] = sid
    ids = {
        "soccer": deportes.get("soccer", 10),
        "basketball": next((v for k, v in deportes.items() if "basketball" in k), None),
        "volleyball": next((v for k, v in deportes.items() if "volleyball" in k and "beach" not in k), None),
    }
    c["deportes"] = ids

    torneos, nombres_torneos, deporte_torneo = {}, {}, {}
    for dep in sorted({l[0] for l in config.LIGAS}):
        sid = ids.get(dep)
        if sid is None:
            avisos.append(f"No encontré el deporte {dep} en OddsPapi")
            continue
        todos = lista(get("tournaments", sportId=sid))
        for _, cat, nom in [l for l in config.LIGAS if l[0] == dep]:
            malas = config.EXCLUIR + ["srl", "simulated", "virtual", "esoccer", "ebasket", "cyber"]
            cands = [t for t in todos
                     if nom in norm(t.get("tournamentName", ""))
                     and cat in norm(t.get("categoryName", ""))
                     and not any(x in norm(f"{t.get('tournamentName', '')} {t.get('categoryName', '')}")
                                 for x in malas)]
            if not cands:
                avisos.append(f"Liga no encontrada: {dep} / {cat or '*'} / {nom}")
                continue
            # Prefiere el nombre exacto (LaLiga antes que LaLiga 2), luego el más corto
            t = min(cands, key=lambda x: (norm(x.get("tournamentName", "")) != nom,
                                          len(x.get("tournamentName", "")),
                                          -(x.get("futureFixtures") or 0)))
            tid = str(t["tournamentId"])
            torneos[f"{dep}|{cat}|{nom}"] = tid
            nombres_torneos[tid] = f"{t.get('categoryName', '')} - {t.get('tournamentName', '')}"
            deporte_torneo[tid] = dep
    c["torneos"], c["nombres_torneos"], c["deporte_torneo"] = torneos, nombres_torneos, deporte_torneo

    mercados = {}
    for m in lista(get("markets", language="es")):
        if m.get("playerProp"):
            continue
        mercados[str(m["marketId"])] = {
            "nombre": m.get("marketName", ""),
            "handicap": m.get("handicap"),
            "resultados": {str(o["outcomeId"]): o.get("outcomeName", "") for o in m.get("outcomes", [])},
        }
    c["mercados"] = mercados
    c.setdefault("participantes", {})
    c["actualizado"] = datetime.now(timezone.utc).isoformat()


def completar_participantes(c: dict, partidos: list[dict]) -> None:
    """Pide nombres de equipos solo si aparecen equipos nuevos (máx. 1 consulta por deporte)."""
    faltan: dict[int, set[str]] = {}
    for p in partidos:
        for k in ("participant1Id", "participant2Id"):
            pid = str(p.get(k))
            if pid and pid not in c["participantes"]:
                faltan.setdefault(p.get("sportId"), set()).add(pid)
    for sid, ids in faltan.items():
        datos = get("participants", sportId=sid)
        if isinstance(datos, dict) and not any(isinstance(v, list) for v in datos.values()):
            pares = datos.items()  # formato {id: nombre}
        else:
            pares = ((_campo(x, "participantId", "id"), _campo(x, "participantName", "name"))
                     for x in lista(datos))
        for pid, nombre in pares:
            if str(pid) in ids and nombre:
                c["participantes"][str(pid)] = nombre


LOTE = Path(__file__).parent / "data" / "lote.json"


def cuotas(torneos: list[str]) -> list[dict]:
    """Pide las cuotas por grupos de ligas. Si OddsPapi rechaza el grupo (400),
    lo parte a la mitad y recuerda el tamaño que funciona para no gastar consultas."""
    casas = ",".join([config.REFERENCIA, config.MI_CASA, config.PAREJA_SUREBET])
    try:
        lote = int(json.loads(LOTE.read_text())["lote"])
    except Exception:
        lote = len(torneos)
    lote = max(1, min(lote, len(torneos)))
    pendientes = [torneos[i:i + lote] for i in range(0, len(torneos), lote)]
    partidos: list[dict] = []
    while pendientes:
        grupo = pendientes.pop(0)
        try:
            partidos += lista(get("odds-by-tournaments", tournamentIds=",".join(grupo), bookmakers=casas))
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 400 and len(grupo) > 1:
                print(f"Grupo de {len(grupo)} ligas rechazado: {e.response.text[:200]}")
                mitad = (len(grupo) + 1) // 2
                lote = min(lote, mitad)
                pendientes = [grupo[:mitad], grupo[mitad:]] + pendientes
                continue
            detalle = e.response.text[:300] if e.response is not None else ""
            print(f"Se omite la liga {grupo}: {e} {detalle}")
    LOTE.parent.mkdir(parents=True, exist_ok=True)
    LOTE.write_text(json.dumps({"lote": lote}))
    print(f"Ligas por consulta: {lote}")
    return partidos
