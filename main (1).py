"""Bot de valor en BetPlay y surebets. Lo ejecuta GitHub Actions varias veces al día."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

import requests

import analisis
import config
import oddspapi

ENVIADAS = Path(__file__).parent / "data" / "enviadas.json"
CO = timezone(timedelta(hours=-5))
CASAS = {"betplay": "BetPlay", "betsson": "Betsson", "bwin": "bwin", "stake": "Stake"}
EMOJI = {"soccer": "⚽", "basketball": "🏀", "volleyball": "🏐"}


def telegram(texto: str) -> None:
    token, chat = os.getenv("TELEGRAM_TOKEN", "").strip(), os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        print("---- [modo prueba] ----\n" + texto)
        return
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": texto, "parse_mode": "HTML",
                            "disable_web_page_preview": True}, timeout=20)
    if r.status_code != 200:
        print("Telegram:", r.status_code, r.text[:300])
    r.raise_for_status()


def pesos(x: float) -> str:
    return "$" + f"{x:,.0f}".replace(",", ".")


def hora_co(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(CO)
        return d.strftime("%d/%m %I:%M %p").lower()
    except Exception:
        return iso


def encabezado(p: dict, cache: dict) -> str:
    tid = str(p.get("tournamentId"))
    dep = cache["deporte_torneo"].get(tid, "")
    eq1 = cache["participantes"].get(str(p.get("participant1Id")), "Local")
    eq2 = cache["participantes"].get(str(p.get("participant2Id")), "Visitante")
    return (f"{EMOJI.get(dep, '🎯')} <b>{escape(cache['nombres_torneos'].get(tid, ''))}</b>\n"
            f"{escape(eq1)} vs {escape(eq2)} — {hora_co(p.get('startTime', ''))}")


def nombre_mercado(info: dict) -> str:
    n = info["nombre"]
    h = info.get("handicap")
    if h not in (None, 0, 0.0) and str(h) not in n:
        n += f" ({h:g})" if isinstance(h, (int, float)) else f" ({h})"
    return n


def msg_valor(p: dict, h: dict, cache: dict) -> str:
    info = cache["mercados"][h["mid"]]
    stake = f"{h['stake'] * 100:.1f} % de tu banca"
    if config.BANCA:
        stake += f" ≈ <b>{pesos(config.BANCA * h['stake'])}</b>"
    return (f"🔵 <b>VALOR EN BETPLAY</b>\n{encabezado(p, cache)}\n\n"
            f"Mercado: {escape(nombre_mercado(info))}\n"
            f"✅ Jugar: <b>{escape(info['resultados'].get(h['oid'], h['oid']))}</b>\n"
            f"💰 BetPlay paga <b>{h['cuota']:.2f}</b> · justa (Pinnacle): {h['justa']:.2f}\n"
            f"📈 Ventaja: <b>{h['ventaja'] * 100:+.1f} %</b>\n"
            f"🎯 Stake: {stake}\n\n"
            f"<i>Verifica que la cuota en BetPlay siga igual antes de apostar.</i>")


def msg_surebet(p: dict, h: dict, cache: dict) -> str:
    info = cache["mercados"][h["mid"]]
    lineas = []
    tope_superado = False
    for oid, (cuota, casa, frac) in h["reparto"].items():
        res = escape(info["resultados"].get(oid, oid))
        if config.MONTO_SUREBET:
            monto = config.MONTO_SUREBET * frac
            tope_superado |= monto * cuota > config.TOPE_PREMIO
            lineas.append(f"• {CASAS.get(casa, casa)}: <b>{res}</b> @ {cuota:.2f} → {pesos(monto)}")
        else:
            lineas.append(f"• {CASAS.get(casa, casa)}: <b>{res}</b> @ {cuota:.2f} → {frac * 100:.1f} % del monto")
    extra = ""
    if config.MONTO_SUREBET:
        extra = f"\nGanancia aprox.: <b>{pesos(config.MONTO_SUREBET * h['ganancia'])}</b> sobre {pesos(config.MONTO_SUREBET)}"
    if tope_superado:
        extra += "\n⚠️ Algún premio supera $2.513.952: te retendrían 20 %. Baja el monto."
    return (f"🟢 <b>SUREBET {h['ganancia'] * 100:.1f} %</b>\n{encabezado(p, cache)}\n\n"
            f"Mercado: {escape(nombre_mercado(info))}\n" + "\n".join(lineas) + extra +
            "\n\n<i>Apuesta primero la cuota más alta y verifica ambas antes.</i>")


def cargar_enviadas() -> dict:
    try:
        return json.loads(ENVIADAS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def guardar_enviadas(d: dict) -> None:
    limite = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat()
    d = {k: v for k, v in d.items() if v >= limite}
    ENVIADAS.parent.mkdir(parents=True, exist_ok=True)
    ENVIADAS.write_text(json.dumps(d, indent=0), encoding="utf-8")


def en_horizonte(p: dict, ahora: datetime) -> bool:
    if p.get("statusId") not in (None, 0, 1):
        return False
    try:
        inicio = datetime.fromisoformat(str(p["startTime"]).replace("Z", "+00:00"))
    except Exception:
        return False
    return ahora + timedelta(minutes=config.MINUTOS_MIN) <= inicio <= ahora + timedelta(days=config.DIAS_MAX)


def main() -> int:
    cache = oddspapi.cargar_cache()
    if oddspapi.cache_vencido(cache):
        avisos: list[str] = []
        oddspapi.refrescar_catalogo(cache, avisos)
        oddspapi.guardar_cache(cache)
        ligas = "\n".join(f"• {n}" for n in sorted(cache["nombres_torneos"].values()))
        telegram(f"📋 <b>Ligas vigiladas</b> ({len(cache['nombres_torneos'])})\n{escape(ligas)}"
                 + ("\n\n⚠️ " + escape("\n⚠️ ".join(avisos)) if avisos else ""))

    torneos = sorted(set(cache.get("torneos", {}).values()))
    if not torneos:
        print("No hay ligas configuradas/encontradas")
        return 1
    partidos = oddspapi.cuotas(torneos)
    ahora = datetime.now(timezone.utc)
    partidos = [p for p in partidos if en_horizonte(p, ahora)]
    oddspapi.completar_participantes(cache, partidos)
    oddspapi.guardar_cache(cache)

    enviadas = cargar_enviadas()
    n_valor = n_sure = 0
    try:
        for p in sorted(partidos, key=lambda x: x.get("startTime", "")):
            for h in analisis.buscar_valor(p, cache["mercados"]) + analisis.buscar_surebets(p, cache["mercados"]):
                clave = f"{h['tipo']}|{p['fixtureId']}|{h['mid']}|{h.get('oid', '')}"
                if clave in enviadas:
                    continue
                telegram(msg_valor(p, h, cache) if h["tipo"] == "valor" else msg_surebet(p, h, cache))
                enviadas[clave] = ahora.isoformat()
                n_valor += h["tipo"] == "valor"
                n_sure += h["tipo"] == "surebet"
    finally:
        guardar_enviadas(enviadas)
    print(f"Partidos revisados: {len(partidos)} | valor: {n_valor} | surebets: {n_sure} | "
          f"consultas usadas: {oddspapi.consultas}")
    return 0


if __name__ == "__main__":
    if "--prueba" in sys.argv:
        telegram("🔔 Bot de valor BetPlay conectado correctamente.")
        sys.exit(0)
    sys.exit(main())
