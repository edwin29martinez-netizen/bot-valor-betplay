"""Configuración del bot. Lo que más se cambia está aquí."""
import os

# Casas: OddsPapi pide una consulta por cada casa.
REFERENCIA = "pinnacle"          # casa "afilada" para calcular la cuota justa
MI_CASA = "betplay"              # donde apuestas
PAREJA_SUREBET = ""              # "" = surebets apagadas (ahorra consultas). Para activar: "betsson"

# Ligas: (deporte, palabra del país/categoría, palabra del nombre del torneo)
# Se buscan sin tildes y sin mayúsculas. Categoría vacía = cualquiera.
LIGAS = [
    ("soccer", "colombia", "primera a"),
    ("soccer", "england", "premier league"),
    ("soccer", "spain", "laliga"),
    ("soccer", "italy", "serie a"),
    ("soccer", "germany", "bundesliga"),
    ("soccer", "", "uefa champions league"),
    ("soccer", "", "copa libertadores"),
    ("basketball", "usa", "nba"),
    ("basketball", "", "euroleague"),
    ("volleyball", "italy", "superlega"),
    ("volleyball", "brazil", "superliga"),
]
EXCLUIR = ["women", "femenin", "u19", "u20", "u21", "u23", "reserve", "youth", "qualification"]

# Filtros de valor
VENTAJA_MINIMA = 0.03     # +3 %
VENTAJA_MAXIMA = 0.20     # más de 20 % suele ser un error de datos o cuota vieja
CUOTA_MAXIMA = 8.0        # cuotas muy altas son muy volátiles
MARGEN_MAX_REFERENCIA = 0.12
FRACCION_KELLY = 0.25     # ¼ de Kelly
STAKE_MAXIMO = 0.02       # nunca más del 2 % de la banca

# Filtros de surebet
SUREBET_MINIMA = 0.01     # +1 %

# Horizonte: partidos que empiezan entre 15 min y 3 días desde ahora
MINUTOS_MIN = 15
DIAS_MAX = 3

# Banca (variables de GitHub). Si no se definen, el bot da solo porcentajes.
BANCA = float(os.getenv("BANCA", "0") or 0)
MONTO_SUREBET = float(os.getenv("MONTO_SUREBET", "0") or 0) or (BANCA * 0.10)
TOPE_PREMIO = 2_513_952   # sobre este premio la casa retiene 20 % (48 UVT 2026)
