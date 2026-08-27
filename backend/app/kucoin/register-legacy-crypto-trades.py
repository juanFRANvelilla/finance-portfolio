"""
register-legacy-crypto-trades.py
---------------------------------
Extrae el historial de ejecuciones (Fills) de KuCoin semana a semana
e inserta las compras en la tabla `asset_transactions` de PostgreSQL.

Uso:
    cd backend/
    python -m app.kucoin.register-legacy-crypto-trades

Requiere las variables de entorno habituales del proyecto (.env):
    DATABASE_URL, KUCOIN_API_KEY, KUCOIN_SECRET, KUCOIN_PASSPHRASE
"""

import os
import time
import uuid
from datetime import datetime, timedelta, date
from decimal import Decimal
from pathlib import Path

import ccxt
from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

# Cargar .env de la raíz del backend
BACKEND_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_ROOT / ".env"
load_dotenv(dotenv_path=ENV_FILE)

# Reutilizamos el engine y SessionLocal ya configurados en el proyecto
from app.core.database import SessionLocal


# ---------------------------------------------------------------------------
# CONFIGURACIÓN GLOBAL
# ---------------------------------------------------------------------------

# ── Regla 1: Fecha de inicio configurable ────────────────────────────────────
# Modifica esta variable para cambiar el rango histórico a procesar.
START_DATE = datetime(2025, 11, 20)

# ── Regla 2: Tasa de fallback USDT→EUR ───────────────────────────────────────
# Si no hay operaciones USDT-EUR en el rango, se usa este valor histórico.
USDT_EUR_FALLBACK_RATE = 0.8535


# ---------------------------------------------------------------------------
# CAPA DE BASE DE DATOS
# ---------------------------------------------------------------------------

def cargar_activos_desde_bd(db: Session) -> dict[str, str]:
    """
    Carga dinámica de activos.

    Consulta `asset_types` y devuelve:
        { exchange_ticker (upper) -> asset_type_id (str) }
    Solo para registros con exchange_ticker informado.
    """
    resultado = db.execute(
        text("SELECT id, exchange_ticker FROM public.asset_types WHERE exchange_ticker IS NOT NULL")
    ).fetchall()

    mapa = {row.exchange_ticker.upper(): str(row.id) for row in resultado}
    print(f"[DB] {len(mapa)} activos cargados: {list(mapa.keys())}")
    return mapa


def cargar_transacciones_existentes(db: Session) -> set[tuple]:
    """
    Idempotencia – carga en memoria las transacciones ya existentes.

    Devuelve un Set de tuplas:
        (str(asset_type_id), str(transaction_date), round(asset_amount, 6))

    Cargarlo una sola vez evita una consulta SELECT por cada fill.
    """
    filas = db.execute(
        text("SELECT asset_type_id, transaction_date, asset_amount FROM public.asset_transactions")
    ).fetchall()

    existentes: set[tuple] = {
        (str(row.asset_type_id), str(row.transaction_date), round(float(row.asset_amount), 6))
        for row in filas
    }
    print(f"[DB] {len(existentes)} transacciones existentes cargadas en memoria.")
    return existentes


def insertar_transacciones_en_lote(db: Session, fills: list[dict]) -> None:
    """
    Inserta todos los fills de la lista en una única transacción de BD.
    """
    for fill in fills:
        db.execute(
            text("""
                INSERT INTO public.asset_transactions
                    (id, asset_type_id, transaction_date, invested_amount,
                     asset_amount, execution_price, fee_amount)
                VALUES
                    (:id, :asset_type_id, :transaction_date, :invested_amount,
                     :asset_amount, :execution_price, :fee_amount)
            """),
            {
                "id": str(uuid.uuid4()),
                "asset_type_id": fill["asset_type_id"],
                "transaction_date": fill["transaction_date"],
                "invested_amount": fill["invested_amount"],
                "asset_amount": fill["asset_amount"],
                "execution_price": fill["execution_price"],
                "fee_amount": fill["fee_amount"],
            },
        )
    db.commit()


# ---------------------------------------------------------------------------
# CAPA DE EXTRACCIÓN (KuCoin)
# ---------------------------------------------------------------------------

def extraer_fills_de_kucoin() -> list[dict]:
    """
    Conecta con la API de KuCoin y extrae todos los Fills semana a semana
    desde START_DATE hasta hoy. Devuelve la lista raw de items de la API.
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

    print(f"Iniciando escaneo desde {START_DATE.strftime('%Y-%m-%d')} hasta hoy...")

    end_date = datetime.now()
    all_fills: list[dict] = []
    current_start = START_DATE

    while current_start < end_date:
        # Ventanas de 6 días para respetar el límite de KuCoin
        current_end = min(current_start + timedelta(days=6), end_date)

        start_ms = int(current_start.timestamp() * 1000)
        end_ms = int(current_end.timestamp() * 1000)

        print(
            f"Consultando ventana: "
            f"{current_start.strftime('%Y-%m-%d')} → {current_end.strftime('%Y-%m-%d')}..."
        )

        try:
            response = exchange.private_get_fills({
                "startAt": start_ms,
                "endAt": end_ms,
                "pageSize": 100,
            })
            items = response.get("data", {}).get("items", [])
            if items:
                all_fills.extend(items)
                print(f"  -> Encontrados {len(items)} trades.")
        except Exception as exc:
            print(f"  [ERROR] Ventana {current_start.strftime('%Y-%m-%d')}: {exc}")

        current_start = current_end + timedelta(seconds=1)
        time.sleep(0.3)

    print(f"\nTotal fills brutos extraídos de KuCoin: {len(all_fills)}")
    return all_fills


# ---------------------------------------------------------------------------
# CAPA DE CÁLCULO: Tasa de cambio USDT → EUR
# ---------------------------------------------------------------------------

def calcular_tasa_usdt_eur(raw_fills: list[dict]) -> float:
    """
    Regla 2 – Cálculo del tipo de cambio puente EUR→USDT.

    Busca todas las compras del par USDT-EUR y calcula la tasa media:
        usdt_eur_rate = total_EUR_gastado / total_USDT_recibido

    Si no hay operaciones USDT-EUR en el rango, usa USDT_EUR_FALLBACK_RATE.
    """
    total_eur_gastado = 0.0
    total_usdt_recibido = 0.0

    for fill in raw_fills:
        symbol: str = fill.get("symbol", "")
        side: str = fill.get("side", "").upper()

        if symbol.upper() == "USDT-EUR" and side == "BUY":
            total_eur_gastado += float(fill.get("funds", 0))
            total_usdt_recibido += float(fill.get("size", 0))

    if total_usdt_recibido > 0:
        rate = total_eur_gastado / total_usdt_recibido
        print(
            f"[RATE] Tasa USDT→EUR calculada desde fills: {rate:.6f} "
            f"({total_eur_gastado:.2f} EUR / {total_usdt_recibido:.2f} USDT)"
        )
        return rate

    print(
        f"[RATE] No hay operaciones USDT-EUR en el rango. "
        f"Usando tasa de fallback: {USDT_EUR_FALLBACK_RATE}"
    )
    return USDT_EUR_FALLBACK_RATE


# ---------------------------------------------------------------------------
# CAPA DE TRANSFORMACIÓN
# ---------------------------------------------------------------------------

def transformar_fills(
    raw_fills: list[dict],
    mapa_activos: dict[str, str],
    existentes: set[tuple],
    usdt_eur_rate: float,
) -> list[dict]:
    """
    Aplica las reglas de negocio de filtrado y mapeo sobre los fills crudos.

    Reglas aplicadas:
        – Solo compras (side == 'BUY')
        – Ignora el par puente USDT-EUR (ya procesado para calcular la tasa)
        – Mapea símbolo → asset_type_id; omite si no existe en BD
        – Convierte invested_amount a EUR según la divisa cotización del par:
              Par en EUR  → invested_amount = funds (directo)
              Par en USDT → invested_amount = funds * usdt_eur_rate
        – execution_price siempre en EUR: invested_amount / size
        – Idempotencia en memoria: omite fills cuya clave ya está en `existentes`
    """
    procesados: list[dict] = []
    omitidos_fiat = 0
    omitidos_sin_activo = 0
    omitidos_duplicados = 0

    for fill in raw_fills:
        symbol: str = fill.get("symbol", "")
        side: str = fill.get("side", "").upper()

        # Solo compras
        if side != "BUY":
            continue

        # Extraer moneda base y de cotización (ej: 'SOL-USDT' → base='SOL', quote='USDT')
        partes = symbol.upper().split("-")
        if len(partes) != 2:
            print(f"  [WARN] Símbolo con formato inesperado: '{symbol}'. Omitido.")
            continue

        base_currency, quote_currency = partes

        # Ignorar el par puente fiat (USDT-EUR ya se usó para calcular la tasa)
        if base_currency == "USDT":
            omitidos_fiat += 1
            continue

        # Buscar UUID del activo en el mapa dinámico
        asset_type_id = mapa_activos.get(base_currency)
        if asset_type_id is None:
            print(
                f"  [WARN] Activo '{base_currency}' (par: {symbol}) no encontrado "
                f"en asset_types. Operación omitida."
            )
            omitidos_sin_activo += 1
            continue

        # Mapeo de campos raw
        created_at_ms = int(fill.get("createdAt", 0))
        transaction_date: date = datetime.utcfromtimestamp(created_at_ms / 1000).date()
        funds = float(fill.get("funds", 0))
        size = float(fill.get("size", 0))
        fee = float(fill.get("fee", 0))

        # ── Regla 3: Conversión a EUR ─────────────────────────────────────────
        if quote_currency == "EUR":
            invested_amount_eur = funds
        elif quote_currency == "USDT":
            invested_amount_eur = funds * usdt_eur_rate
        else:
            # Divisa de cotización desconocida: loguear y omitir
            print(
                f"  [WARN] Divisa de cotización desconocida '{quote_currency}' "
                f"en par {symbol}. Operación omitida."
            )
            omitidos_sin_activo += 1
            continue

        # execution_price siempre en EUR
        execution_price_eur = invested_amount_eur / size if size > 0 else 0.0

        # ── Regla 4: Idempotencia en memoria ──────────────────────────────────
        clave = (str(asset_type_id), str(transaction_date), round(size, 6))
        if clave in existentes:
            print(
                f"  [SKIP] Duplicado en memoria: {transaction_date} | "
                f"{symbol} | cantidad={round(size, 6)}"
            )
            omitidos_duplicados += 1
            continue

        # Marcar como procesado en el Set para evitar duplicados dentro del mismo lote
        existentes.add(clave)

        procesados.append({
            "symbol": symbol,
            "asset_type_id": asset_type_id,
            "transaction_date": transaction_date,
            "invested_amount": Decimal(str(round(invested_amount_eur, 8))),
            "asset_amount": Decimal(str(size)),
            "execution_price": Decimal(str(round(execution_price_eur, 8))),
            "fee_amount": Decimal(str(fee)),
        })

    print(
        f"\nTransformación completada:"
        f"\n  - Fills listos para insertar : {len(procesados)}"
        f"\n  - Omitidos (puente fiat)      : {omitidos_fiat}"
        f"\n  - Omitidos (activo no en BD)  : {omitidos_sin_activo}"
        f"\n  - Omitidos (duplicados)       : {omitidos_duplicados}"
    )
    return procesados


# ---------------------------------------------------------------------------
# PUNTO DE ENTRADA
# ---------------------------------------------------------------------------

def main() -> None:
    # ── Paso 1: Extraer todos los fills desde KuCoin ──────────────────────────
    raw_fills = extraer_fills_de_kucoin()

    if not raw_fills:
        print(
            "\nNo se encontraron operaciones en Spot tras escanear todo el periodo.\n"
            "IMPORTANTE: Si no sale nada, puede que tus compras se hicieran mediante "
            "la opción 'Convertir' (OTC) y no como órdenes de mercado."
        )
        return

    # ── Paso 2: Calcular tasa de cambio USDT→EUR desde los propios fills ──────
    usdt_eur_rate = calcular_tasa_usdt_eur(raw_fills)

    # ── Paso 3: Abrir sesión de BD ─────────────────────────────────────────────
    with SessionLocal() as db:
        mapa_activos = cargar_activos_desde_bd(db)
        if not mapa_activos:
            print("[ERROR] No se pudieron cargar activos desde la BD. Abortando.")
            return

        # Cargar transacciones existentes en memoria (idempotencia O(1))
        existentes = cargar_transacciones_existentes(db)

        # ── Paso 4: Transformar y filtrar fills ───────────────────────────────
        fills_a_insertar = transformar_fills(raw_fills, mapa_activos, existentes, usdt_eur_rate)

        if not fills_a_insertar:
            print("\nNo hay operaciones nuevas para insertar. Fin.")
            return

        # ── Paso 5: Insertar en lote ──────────────────────────────────────────
        print(f"\nInsertando {len(fills_a_insertar)} operaciones en asset_transactions...\n")
        for fill in fills_a_insertar:
            print(
                f"  [OK] {fill['transaction_date']} | {fill['symbol']} | "
                f"invertido={fill['invested_amount']} EUR | "
                f"precio={fill['execution_price']} EUR | "
                f"cantidad={fill['asset_amount']}"
            )

        try:
            insertar_transacciones_en_lote(db, fills_a_insertar)
        except Exception as exc:
            print(f"\n[ERROR CRÍTICO] Fallo durante la inserción en BD: {exc}")
            raise

    omitidos_total = (
        len([f for f in raw_fills if f.get("side", "").upper() == "BUY"])
        - len(fills_a_insertar)
    )
    print(
        f"\n{'='*52}"
        f"\nPROCESO FINALIZADO"
        f"\n  Tasa USDT→EUR utilizada : {usdt_eur_rate:.6f}"
        f"\n  Insertados              : {len(fills_a_insertar)}"
        f"\n  No insertados (total)   : {omitidos_total}"
        f"\n{'='*52}"
    )


if __name__ == "__main__":
    main()