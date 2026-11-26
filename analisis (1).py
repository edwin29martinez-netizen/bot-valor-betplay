"""Cálculos: cuota justa (sin margen), valor esperado, Kelly y surebets."""
from __future__ import annotations

import config


def precios_mercado(libro: dict, mid: str) -> dict[str, float]:
    """Precios activos de un mercado (solo líneas sin jugador, player '0')."""
    if not libro or libro.get("suspended") or libro.get("bookmakerIsActive") is False:
        return {}
    m = (libro.get("markets") or {}).get(mid) or {}
    if m.get("marketActive") is False:
        return {}
    salida = {}
    for oid, o in (m.get("outcomes") or {}).items():
        p = ((o or {}).get("players") or {}).get("0") or {}
        if p.get("active", True) and p.get("price") and float(p["price"]) > 1.0:
            salida[oid] = float(p["price"])
    return salida


def cuota_justa(ref: dict[str, float], n_resultados: int) -> dict[str, float] | None:
    """Quita el margen de la referencia (método proporcional)."""
    if len(ref) < 2 or len(ref) != n_resultados:
        return None
    suma = sum(1 / c for c in ref.values())
    if not (1.0 <= suma <= 1 + config.MARGEN_MAX_REFERENCIA):
        return None
    return {o: c * suma for o, c in ref.items()}


def kelly(cuota: float, justa: float) -> float:
    p = 1 / justa
    b = cuota - 1
    f = (b * p - (1 - p)) / b
    return max(0.0, min(f * config.FRACCION_KELLY, config.STAKE_MAXIMO))


def buscar_valor(partido: dict, mercados_info: dict) -> list[dict]:
    libros = partido.get("bookmakerOdds") or {}
    ref_libro, mia = libros.get(config.REFERENCIA), libros.get(config.MI_CASA)
    if not ref_libro or not mia:
        return []
    hallazgos = []
    for mid in (mia.get("markets") or {}):
        info = mercados_info.get(mid)
        if not info:
            continue
        justas = cuota_justa(precios_mercado(ref_libro, mid), len(info["resultados"]) or 0)
        if not justas:
            continue
        for oid, cuota in precios_mercado(mia, mid).items():
            if oid not in justas or cuota > config.CUOTA_MAXIMA:
                continue
            ventaja = cuota / justas[oid] - 1
            if config.VENTAJA_MINIMA <= ventaja <= config.VENTAJA_MAXIMA:
                hallazgos.append({"tipo": "valor", "mid": mid, "oid": oid, "cuota": cuota,
                                  "justa": justas[oid], "ventaja": ventaja,
                                  "stake": kelly(cuota, justas[oid])})
    return hallazgos


def buscar_surebets(partido: dict, mercados_info: dict) -> list[dict]:
    libros = partido.get("bookmakerOdds") or {}
    casas = [c for c in (config.MI_CASA, config.PAREJA_SUREBET) if c in libros]
    if len(casas) < 2:
        return []
    hallazgos = []
    mids = set()
    for c in casas:
        mids |= set((libros[c].get("markets") or {}).keys())
    for mid in mids:
        info = mercados_info.get(mid)
        if not info or len(info["resultados"]) < 2:
            continue
        mejor: dict[str, tuple[float, str]] = {}
        for c in casas:
            for oid, cuota in precios_mercado(libros[c], mid).items():
                if oid not in mejor or cuota > mejor[oid][0]:
                    mejor[oid] = (cuota, c)
        if len(mejor) != len(info["resultados"]):
            continue
        if len({c for _, c in mejor.values()}) < 2:
            continue  # todo en una casa no es surebet
        suma = sum(1 / c for c, _ in mejor.values())
        ganancia = 1 / suma - 1
        if ganancia >= config.SUREBET_MINIMA:
            reparto = {oid: (c, casa, (1 / c) / suma) for oid, (c, casa) in mejor.items()}
            hallazgos.append({"tipo": "surebet", "mid": mid, "ganancia": ganancia, "reparto": reparto})
    return hallazgos
