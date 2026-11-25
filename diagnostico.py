"""Diagnóstico con la API oficial de OddsPapi (plan gratis).

Responde tres preguntas usando ~5 consultas:
  1. ¿Qué casas colombianas trae OddsPapi?
  2. ¿Vienen BetPlay y Pinnacle en el mismo partido?
  3. ¿Cómo se ve el cálculo de valor en un partido real?
Uso: python diagnostico.py   (necesita ODDSPAPI_KEY; Telegram es opcional)
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import requests

BASE = "https://api.oddspapi.io/v4"
API_KEY = os.getenv("ODDSPAPI_KEY", "").strip()
COLOMBIANAS = ["betplay", "wplay", "rushbet", "codere", "betsson", "yajuego", "rivalo",
               "zamba", "luckia", "sportium", "bwin", "megapuesta", "wonderbet", "fullreto",
               "stake", "betano", "1xbet"]
informe: list[str] = []
consultas = 0


def log(linea: str = "") -> None:
    print(linea)
    informe.append(linea)


def api(ruta: str, **params):
    global consultas
    consultas += 1
    params["apiKey"] = API_KEY
    r = requests.get(f"{BASE}/{ruta}", params=params, timeout=30)
    cupo = {k: v for k, v in r.headers.items() if "limit" in k.lower() or "remaining" in k.lower()}
    if cupo:
        log(f"   (cupo: {cupo})")
    if r.status_code != 200:
        log(f"   {ruta}: HTTP {r.status_code} {r.text[:200]}")
        return None
    return r.json()


def lista(data):
    """Algunas respuestas vienen como lista y otras como dict con una lista adentro."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for v in data.values():
            if isinstance(v, list):
                return v
    return []


def cuotas_1x2(libro: dict) -> list[float] | None:
    m = (libro.get("markets") or {}).get("101")
    if not m:
        return None
    precios = []
    for o in ("101", "102", "103"):
        p = ((m.get("outcomes") or {}).get(o, {}).get("players") or {}).get("0") or {}
        if not p.get("price"):
            return None
        precios.append(float(p["price"]))
    return precios


def main() -> None:
    if not API_KEY:
        log("❌ Falta el secreto ODDSPAPI_KEY")
        return

    # 1) Casas disponibles
    log("1) CASAS COLOMBIANAS EN ODDSPAPI")
    casas = lista(api("bookmakers"))
    slugs = []
    for c in casas:
        slug = str(c.get("slug") or c.get("bookmaker") or c.get("id") or c) if isinstance(c, dict) else str(c)
        slugs.append(slug)
    log(f"   total de casas: {len(slugs)}")
    encontradas = sorted({s for s in slugs if any(k in s.lower() for k in COLOMBIANAS)})
    log("   " + (", ".join(encontradas) if encontradas else "ninguna reconocida"))
    log(f"   pinnacle: {'sí' if 'pinnacle' in slugs else 'no'}")

    # 2) Un torneo con partidos próximos (Colombia primero, si no Premier)
    log("\n2) BUSCANDO UN PARTIDO CON CUOTAS")
    torneos = lista(api("tournaments", sportId=10))
    def puntaje(t):
        cat, nom = str(t.get("categoryName", "")).lower(), str(t.get("tournamentName", "")).lower()
        if "colombia" in cat and "primera" in nom:
            return 0
        if "england" in cat and "premier" in nom:
            return 1
        return 2
    candidatos = sorted([t for t in torneos if t.get("futureFixtures")], key=puntaje)[:2]
    hoy = datetime.now(timezone.utc).date()
    partido = None
    for t in candidatos:
        log(f"   torneo: {t.get('categoryName')} - {t.get('tournamentName')}")
        fx = lista(api("fixtures", tournamentId=t["tournamentId"],
                       **{"from": hoy.isoformat(), "to": (hoy + timedelta(days=7)).isoformat()}))
        con_cuotas = [f for f in fx if f.get("hasOdds")]
        if con_cuotas:
            partido = con_cuotas[0]
            break
    if not partido:
        log("   no se encontró partido con cuotas en los próximos 7 días")
        return
    log(f"   partido: {partido.get('participant1Name')} vs {partido.get('participant2Name')} "
        f"({partido.get('startTime')})")

    # 3) Cuotas del partido
    log("\n3) CUOTAS 1X2 DEL PARTIDO")
    libros = (api("odds", fixtureId=partido["fixtureId"]) or {}).get("bookmakerOdds", {}) or {}
    log(f"   casas con cuotas en este partido: {len(libros)}")
    for slug in sorted(libros):
        if slug == "pinnacle" or any(k in slug.lower() for k in COLOMBIANAS):
            log(f"   {slug}: {cuotas_1x2(libros[slug]) or 'sin 1X2'}")

    pin, bp = cuotas_1x2(libros.get("pinnacle", {})), cuotas_1x2(libros.get("betplay", {}))
    if pin and bp:
        inv = [1 / c for c in pin]
        justas = [sum(inv) / x for x in inv]  # quita el margen de Pinnacle
        log("\n   VALOR EN BETPLAY (vs cuota justa de Pinnacle):")
        for nombre, j, b in zip(("Local", "Empate", "Visitante"), justas, bp):
            log(f"   {nombre}: BetPlay {b:.2f} | justa {j:.2f} | ventaja {(b / j - 1) * 100:+.1f}%")
    else:
        log("   faltan cuotas de Pinnacle o BetPlay en este partido")


def enviar_telegram(texto: str) -> None:
    token, chat = os.getenv("TELEGRAM_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")
    if token and chat:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": texto[:4000]}, timeout=20)
        print("Telegram:", r.status_code)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ Error: {type(e).__name__}: {e}")
    log(f"\nConsultas usadas: {consultas}")
    enviar_telegram("🔎 Diagnóstico OddsPapi\n\n" + "\n".join(informe))
