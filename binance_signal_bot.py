"""
Binance Signal Bot
==================

Bot de SOLO SEÑALES (no ejecuta órdenes). Escanea las principales
criptomonedas listadas contra USDT en Binance, calcula indicadores
técnicos (RSI, medias móviles SMA20/SMA50, volumen) y te avisa
cuándo una moneda muestra una señal de compra o de venta, junto con
un precio objetivo (take profit) y un stop loss sugeridos.

⚠️ IMPORTANTE - LEER ANTES DE USAR:
- Esto NO es asesoramiento financiero. Es una herramienta de apoyo
  basada en análisis técnico clásico, que puede fallar.
- El bot NO compra ni vende nada. Solo te muestra información para
  que decidas vos.
- Usa solo datos públicos de Binance (no necesita API key ni
  conexión a tu cuenta).
- El mercado cripto es muy volátil. Nunca inviertas más de lo que
  estás dispuesto a perder, y considerá siempre el riesgo.

Requisitos:
    pip install requests pandas

Uso básico:
    python binance_signal_bot.py                  # un escaneo único
    python binance_signal_bot.py --loop --minutes 15   # escaneo cada 15 min
"""

import argparse
import csv
import os
import time
import json
from datetime import datetime, timezone

import pandas as pd
import requests

BASE_URL = "https://api.binance.com"
LOG_FILE = "señales_binance.csv"
JSON_FILE = "señales_binance.json"


# ----------------------------------------------------------------------
# Funciones de datos
# ----------------------------------------------------------------------

def obtener_top_pares_usdt(cantidad=30, min_volumen_usdt=5_000_000):
    """
    Devuelve los pares XXX/USDT con mayor volumen de las últimas 24h,
    filtrando los de muy baja liquidez (más riesgo de manipulación
    y de slippage).
    """
    resp = requests.get(f"{BASE_URL}/api/v3/ticker/24hr", timeout=15)
    resp.raise_for_status()
    data = resp.json()

    pares = [
        d for d in data
        if d["symbol"].endswith("USDT")
        and not d["symbol"].endswith("UPUSDT")      # excluye tokens apalancados
        and not d["symbol"].endswith("DOWNUSDT")
        and not d["symbol"].endswith("BUSDUSDT")
        and float(d["quoteVolume"]) >= min_volumen_usdt
    ]
    pares.sort(key=lambda d: float(d["quoteVolume"]), reverse=True)
    return [d["symbol"] for d in pares[:cantidad]]


def obtener_velas(symbol, intervalo="4h", limite=150):
    """Descarga velas (klines) para un símbolo dado."""
    params = {"symbol": symbol, "interval": intervalo, "limit": limite}
    resp = requests.get(f"{BASE_URL}/api/v3/klines", params=params, timeout=15)
    resp.raise_for_status()
    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_volume", "trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]
    df = pd.DataFrame(resp.json(), columns=cols)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = df[c].astype(float)
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df


# ----------------------------------------------------------------------
# Indicadores técnicos
# ----------------------------------------------------------------------

def calcular_rsi(close, periodo=14):
    delta = close.diff()
    ganancia = delta.clip(lower=0)
    perdida = -delta.clip(upper=0)
    avg_gain = ganancia.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    avg_loss = perdida.ewm(alpha=1 / periodo, min_periods=periodo).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi


def calcular_atr(df, periodo=14):
    high, low, close = df["high"], df["low"], df["close"]
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / periodo, min_periods=periodo).mean()


def analizar(df):
    df = df.copy()
    df["sma20"] = df["close"].rolling(20).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["rsi"] = calcular_rsi(df["close"])
    df["atr"] = calcular_atr(df)
    df["vol_avg20"] = df["volume"].rolling(20).mean()
    return df


# ----------------------------------------------------------------------
# Lógica de señales
# ----------------------------------------------------------------------

def generar_señal(df):
    """
    Combina 3 condiciones para reducir señales falsas:
      1. Tendencia: SMA20 vs SMA50 (cruce alcista/bajista)
      2. Momentum: RSI saliendo de zona de sobreventa/sobrecompra
      3. Confirmación: volumen actual por encima del promedio

    Devuelve un dict con la señal, o None si no hay nada claro.
    """
    if len(df) < 55:
        return None

    actual = df.iloc[-1]
    previo = df.iloc[-2]

    if pd.isna(actual["sma50"]) or pd.isna(actual["rsi"]):
        return None

    cruce_alcista = previo["sma20"] <= previo["sma50"] and actual["sma20"] > actual["sma50"]
    cruce_bajista = previo["sma20"] >= previo["sma50"] and actual["sma20"] < actual["sma50"]

    rsi_saliendo_sobreventa = previo["rsi"] < 30 <= actual["rsi"]
    rsi_entrando_sobrecompra = actual["rsi"] >= 70

    volumen_confirma = actual["volume"] > actual["vol_avg20"] * 1.2

    precio = actual["close"]
    atr = actual["atr"]

    # --- Señal de COMPRA ---
    if (cruce_alcista or rsi_saliendo_sobreventa) and actual["rsi"] < 65 and volumen_confirma:
        objetivo = precio + atr * 2       # take profit ≈ 2x ATR
        stop = precio - atr * 1.2         # stop loss ≈ 1.2x ATR
        fuerza = "Fuerte" if (cruce_alcista and rsi_saliendo_sobreventa) else "Moderada"
        return {
            "tipo": "COMPRA",
            "fuerza": fuerza,
            "precio_actual": precio,
            "precio_objetivo": objetivo,
            "stop_loss": stop,
            "rsi": actual["rsi"],
        }

    # --- Señal de VENTA / TOMA DE GANANCIA ---
    if cruce_bajista or rsi_entrando_sobrecompra:
        objetivo = precio - atr * 2
        fuerza = "Fuerte" if (cruce_bajista and rsi_entrando_sobrecompra) else "Moderada"
        return {
            "tipo": "VENTA",
            "fuerza": fuerza,
            "precio_actual": precio,
            "precio_objetivo": objetivo,
            "stop_loss": precio + atr * 1.2,
            "rsi": actual["rsi"],
        }

    return None


# ----------------------------------------------------------------------
# Escaneo principal
# ----------------------------------------------------------------------

def escanear(cantidad_pares=30, intervalo_vela="4h"):
    print(f"\n{'=' * 70}")
    print(f"Escaneo: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'=' * 70}")

    pares = obtener_top_pares_usdt(cantidad=cantidad_pares)
    señales_encontradas = []

    for symbol in pares:
        try:
            df = obtener_velas(symbol, intervalo=intervalo_vela)
            df = analizar(df)
            señal = generar_señal(df)
            if señal:
                señal["symbol"] = symbol
                señales_encontradas.append(señal)
        except Exception as e:
            print(f"  (omitido {symbol}: {e})")
        time.sleep(0.15)  # respeta los límites de la API de Binance

    if not señales_encontradas:
        print("\nNo se encontraron señales claras en este escaneo.")
        return []

    print(f"\n{len(señales_encontradas)} señal(es) encontrada(s):\n")
    for s in señales_encontradas:
        emoji = "🟢" if s["tipo"] == "COMPRA" else "🔴"
        print(
            f"{emoji} {s['symbol']:<12} {s['tipo']:<7} ({s['fuerza']:<9}) "
            f"| Precio: {s['precio_actual']:.6f} "
            f"| Objetivo: {s['precio_objetivo']:.6f} "
            f"| Stop loss: {s['stop_loss']:.6f} "
            f"| RSI: {s['rsi']:.1f}"
        )

    guardar_log(señales_encontradas)
    return señales_encontradas


def guardar_log(señales):
    """Guarda señales en CSV y JSON"""
    existe = os.path.isfile(LOG_FILE)
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not existe:
            writer.writerow([
                "timestamp_utc", "symbol", "tipo", "fuerza",
                "precio_actual", "precio_objetivo", "stop_loss", "rsi"
            ])
        ts = datetime.now(timezone.utc).isoformat()
        for s in señales:
            writer.writerow([
                ts, s["symbol"], s["tipo"], s["fuerza"],
                f"{s['precio_actual']:.8f}",
                f"{s['precio_objetivo']:.8f}",
                f"{s['stop_loss']:.8f}",
                f"{s['rsi']:.2f}"
            ])
    
    # También guardar en JSON para el dashboard
    guardar_json(señales)


def guardar_json(señales):
    """Guarda señales en JSON para el dashboard web"""
    ts = datetime.now(timezone.utc).isoformat()
    
    datos = {
        "timestamp": ts,
        "señales": [
            {
                "symbol": s["symbol"],
                "tipo": s["tipo"],
                "fuerza": s["fuerza"],
                "precio_actual": round(s["precio_actual"], 8),
                "precio_objetivo": round(s["precio_objetivo"], 8),
                "stop_loss": round(s["stop_loss"], 8),
                "rsi": round(s["rsi"], 2)
            }
            for s in señales
        ]
    }
    
    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(datos, f, indent=2, ensure_ascii=False)


# ----------------------------------------------------------------------
# Punto de entrada
# ----------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Bot de señales de Binance (RSI + SMA + volumen)")
    parser.add_argument("--pares", type=int, default=30, help="Cantidad de pares USDT a analizar (por volumen)")
    parser.add_argument("--velas", type=str, default="4h", help="Temporalidad de las velas: 15m, 1h, 4h, 1d, etc.")
    parser.add_argument("--loop", action="store_true", help="Ejecutar en bucle continuo")
    parser.add_argument("--minutos", type=int, default=15, help="Minutos entre cada escaneo si --loop está activo")
    args = parser.parse_args()

    print("Bot de señales de Binance — SOLO INFORMATIVO, no ejecuta órdenes.")
    print("Este bot no es asesoramiento financiero. Operá bajo tu propio criterio.\n")

    if args.loop:
        while True:
            try:
                escanear(cantidad_pares=args.pares, intervalo_vela=args.velas)
            except Exception as e:
                print(f"Error en el escaneo: {e}")
            print(f"\nEsperando {args.minutos} minutos para el próximo escaneo...")
            time.sleep(args.minutos * 60)
    else:
        escanear(cantidad_pares=args.pares, intervalo_vela=args.velas)


if __name__ == "__main__":
    main()
