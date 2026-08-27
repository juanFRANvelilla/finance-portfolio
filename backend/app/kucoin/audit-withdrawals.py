"""
audit-withdrawals.py
---------------------------------
Script de auditoría de solo lectura (Read-Only) para extraer y listar 
el historial de retiros de KuCoin y sus comisiones de red.

Uso:
    cd backend/
    python -m app.kucoin.audit-withdrawals

Requiere las variables de entorno habituales del proyecto (.env):
    KUCOIN_API_KEY, KUCOIN_SECRET, KUCOIN_PASSPHRASE
"""

import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import ccxt
from dotenv import load_dotenv

# Cargar .env de la raíz del backend
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_ROOT / ".env"
load_dotenv(dotenv_path=ENV_FILE)

# Configuración global
START_DATE = datetime(2025, 11, 1)

def extraer_retiros_de_kucoin() -> list[dict]:
    """
    Conecta con la API de KuCoin y extrae todos los retiros (withdrawals)
    semana a semana / mes a mes desde START_DATE hasta hoy.
    """
    api_key = os.getenv("KUCOIN_API_KEY")
    secret = os.getenv("KUCOIN_SECRET")
    passphrase = os.getenv("KUCOIN_PASSPHRASE")

    if not api_key or not secret or not passphrase:
        raise ValueError(
            f"Faltan credenciales de KuCoin en {ENV_FILE}. "
            f"Define KUCOIN_API_KEY, KUCOIN_SECRET y KUCOIN_PASSPHRASE."
        )

    exchange = ccxt.kucoin({
        "apiKey": api_key,
        "secret": secret,
        "password": passphrase,
        "enableRateLimit": True,
    })

    print(f"Iniciando escaneo de retiros desde {START_DATE.strftime('%Y-%m-%d')} hasta hoy...\n")

    end_date = datetime.now()
    all_withdrawals: list[dict] = []
    current_start = START_DATE

    # KuCoin withdrawals API soporta ventanas de búsqueda. Usaremos 30 días.
    while current_start < end_date:
        current_end = min(current_start + timedelta(days=30), end_date)
        
        start_ms = int(current_start.timestamp() * 1000)
        end_ms = int(current_end.timestamp() * 1000)

        print(f"Consultando ventana: {current_start.strftime('%Y-%m-%d')} → {current_end.strftime('%Y-%m-%d')}...")

        try:
            # Extraemos retiros para todas las monedas
            response = exchange.fetch_withdrawals(
                code=None,
                since=start_ms,
                limit=100,
                params={'endAt': end_ms}
            )
            if response:
                all_withdrawals.extend(response)
                print(f"  -> Encontrados {len(response)} retiros.")
        except Exception as exc:
            print(f"  [ERROR] Ventana {current_start.strftime('%Y-%m-%d')}: {exc}")

        current_start = current_end + timedelta(seconds=1)
        time.sleep(0.3)

    return all_withdrawals

def main() -> None:
    withdrawals = extraer_retiros_de_kucoin()

    if not withdrawals:
        print("\nNo se encontraron retiros en el periodo especificado.")
        return

    print(f"\n{'='*80}")
    print(f"{'FECHA':<20} | {'ACTIVO':<8} | {'CANTIDAD':<15} | {'FEE':<15} | {'RED (CHAIN)':<15}")
    print(f"{'-'*80}")

    total_eth_fees = 0.0

    for w in withdrawals:
        # ccxt devuelve datetime en formato ISO string
        dt_str = w.get('datetime', '')
        if dt_str:
            # Limpiamos el string para dejarlo como YYYY-MM-DD HH:MM
            try:
                dt_obj = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
                fecha = dt_obj.strftime("%Y-%m-%d %H:%M")
            except Exception:
                fecha = dt_str[:16]
        else:
            fecha = "Desconocida"

        activo = w.get('currency', 'UNKNOWN')
        cantidad = float(w.get('amount', 0.0))
        fee = float(w.get('fee', {}).get('cost', 0.0))
        
        # Intentamos obtener la red de la info original
        info = w.get('info', {})
        red = info.get('chain', info.get('network', 'N/A'))

        print(f"{fecha:<20} | {activo:<8} | {cantidad:<15.6f} | {fee:<15.6f} | {red:<15}")

        if activo == 'ETH':
            total_eth_fees += fee

    print(f"{'='*80}\n")
    print(f"TOTAL COMISIONES PAGADAS (FEES) EXCLUSIVAMENTE PARA ETH: {total_eth_fees:.6f} ETH")
    print("\nProceso de auditoría finalizado.")

if __name__ == "__main__":
    main()
