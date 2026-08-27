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
# CAPA DE BASE DE DATOS
# ---------------------------------------------------------------------------

def cargar_activos_desde_bd(db: Session) -> dict[str, str]:
    """
    Regla 1 – Carga dinámica de activos.

    Consulta `asset_types` y devuelve un diccionario
    { exchange_ticker -> asset_type_id (str) }
    solo para los registros que tengan exchange_ticker informado.
    """
    resultado = db.execute(
        text("SELECT id, exchange_ticker FROM public.asset_types WHERE exchange_ticker IS NOT NULL")
    ).fetchall()

    mapa = {row.exchange_ticker.upper(): str(row.id) for row in resultado}
    print(f"[DB] {len(mapa)} activos cargados: {list(mapa.keys())}")
    return mapa


def ya_existe_transaccion(
    db: Session,
    asset_type_id: str,
    transaction_date: date,
    asset_amount: Decimal,
) -> bool:
    """
    Regla 6 – Idempotencia.

    Comprueba si ya existe una fila en `asset_transactions` con la misma
    combinación de (asset_type_id, transaction_date, asset_amount).
    """
    fila = db.execute(
        text("""
            SELECT 1
            FROM public.asset_transactions
            WHERE asset_type_id = :asset_type_id
              AND transaction_date = :transaction_date
              AND asset_amount = :asset_amount
            LIMIT 1
        """),
        {
            "asset_type_id": asset_type_id,
            "transaction_date": transaction_date,
            "asset_amount": asset_amount,
        },
    ).fetchone()
    return fila is not None


def insertar_transaccion(
    db: Session,
    asset_type_id: str,
    transaction_date: date,
    invested_amount: Decimal,
    asset_amount: Decimal,
    execution_price: Decimal,
    fee_amount: Decimal,
) -> None:
    """Inserta una única fila en `asset_transactions`."""
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
            "asset_type_id": asset_type_id,
            "transaction_date": transaction_date,
            "invested_amount": invested_amount,
            "asset_amount": asset_amount,
            "execution_price": execution_price,
            "fee_amount": fee_amount,
        },
    )


def persistir_fills(db: Session, fills_procesados: list[dict]) -> tuple[int, int]:
    """
    Itera la lista de fills ya filtrados y mapeados e intenta insertar cada uno.

    Devuelve (insertados, omitidos_duplicados).
    """
    insertados = 0
    omitidos = 0

    for fill in fills_procesados:
        if ya_existe_transaccion(
            db,
            fill["asset_type_id"],
            fill["transaction_date"],
            fill["asset_amount"],
        ):
            print(
                f"  [SKIP] Ya existe: {fill['transaction_date']} | "
                f"{fill['symbol']} | cantidad={fill['asset_amount']}"
            )
            omitidos += 1
            continue

        insertar_transaccion(
            db,
            asset_type_id=fill["asset_type_id"],
            transaction_date=fill["transaction_date"],
            invested_amount=fill["invested_amount"],
            asset_amount=fill["asset_amount"],
            execution_price=fill["execution_price"],
            fee_amount=fill["fee_amount"],
        )
        print(
            f"  [OK]   Insertado: {fill['transaction_date']} | "
            f"{fill['symbol']} | precio={fill['execution_price']} | "
            f"cantidad={fill['asset_amount']}"
        )
        insertados += 1

    db.commit()
    return insertados, omitidos


# ---------------------------------------------------------------------------
# CAPA DE EXTRACCIÓN (KuCoin)
# ---------------------------------------------------------------------------

def extraer_fills_de_kucoin() -> list[dict]:
    """
    Conecta con la API de KuCoin y extrae todos los Fills semana a semana.
    Devuelve la lista raw de items tal como los devuelve la API.
    """
    api_key = os.getenv("KUCOIN_API_KEY")
    secret = os.getenv("KUCOIN_SECRET")
    passphrase = os.getenv("KUCOIN_PASSPHRASE")

    if not api_key or not secret or not passphrase:
        raise ValueError(
            f"Faltan credenciales de KuCoin en las variables de entorno / {ENV_FILE}. "
            f"Asegúrate de definir KUCOIN_API_KEY, KUCOIN_SECRET y KUCOIN_PASSPHRASE."
        )

    exchange = ccxt.kucoin({
        "apiKey": api_key,
        "secret": secret,
        "password": passphrase,
        "enableRateLimit": True,
    })

    print("Iniciando escaneo de ejecuciones (Fills) semana a semana...")

    start_date = datetime(2025, 11, 1)
    end_date = datetime.now()

    all_fills: list[dict] = []
    current_start = start_date

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
# CAPA DE TRANSFORMACIÓN
# ---------------------------------------------------------------------------

def transformar_fills(raw_fills: list[dict], mapa_activos: dict[str, str]) -> list[dict]:
    """
    Aplica las reglas de negocio de filtrado y mapeo sobre los fills crudos.

    Reglas aplicadas:
        2 – Solo compras (side == 'buy' / 'BUY')
        3 – Ignorar puentes fiat (par USDT-EUR o moneda base USDT)
        4 – Mapear símbolo a asset_type_id; omitir si no existe en la BD
        5 – Mapear campos al esquema de la tabla
    """
    procesados: list[dict] = []
    omitidos_fiat = 0
    omitidos_sin_activo = 0

    for fill in raw_fills:
        symbol: str = fill.get("symbol", "")
        side: str = fill.get("side", "").upper()

        # Regla 2 – Solo compras
        if side != "BUY":
            continue

        # Extraer moneda base del par (ej. 'BTC-EUR' -> 'BTC')
        partes = symbol.split("-")
        base_currency = partes[0].upper() if partes else ""

        # Regla 3 – Ignorar puentes fiat/stablecoin (USDT-EUR, USDT-*)
        if base_currency == "USDT":
            omitidos_fiat += 1
            continue

        # Regla 4 – Buscar en el mapa dinámico de activos
        asset_type_id = mapa_activos.get(base_currency)
        if asset_type_id is None:
            print(
                f"  [WARN] Activo '{base_currency}' (par: {symbol}) no encontrado "
                f"en asset_types. Operación omitida."
            )
            omitidos_sin_activo += 1
            continue

        # Regla 5 – Mapeo de campos
        created_at_ms = int(fill.get("createdAt", 0))
        transaction_date = datetime.utcfromtimestamp(created_at_ms / 1000).date()

        procesados.append({
            "symbol": symbol,
            "asset_type_id": asset_type_id,
            "transaction_date": transaction_date,
            "invested_amount": Decimal(str(fill.get("funds", 0))),
            "asset_amount": Decimal(str(fill.get("size", 0))),
            "execution_price": Decimal(str(fill.get("price", 0))),
            "fee_amount": Decimal(str(fill.get("fee", 0))),
        })

    print(
        f"\nTransformación completada:"
        f"\n  - Fills listos para insertar : {len(procesados)}"
        f"\n  - Omitidos (puente fiat)      : {omitidos_fiat}"
        f"\n  - Omitidos (activo no en BD)  : {omitidos_sin_activo}"
    )
    return procesados


# ---------------------------------------------------------------------------
# PUNTO DE ENTRADA
# ---------------------------------------------------------------------------

def main() -> None:
    # 1. Extraer fills desde KuCoin
    raw_fills = extraer_fills_de_kucoin()

    if not raw_fills:
        print(
            "\nNo se encontraron operaciones en Spot tras escanear todo el periodo.\n"
            "IMPORTANTE: Si no sale nada, puede que tus compras se hicieran mediante "
            "la opción 'Convertir' (OTC) y no como órdenes de mercado."
        )
        return

    # 2. Abrir sesión de BD y cargar mapa de activos
    with SessionLocal() as db:
        mapa_activos = cargar_activos_desde_bd(db)

        if not mapa_activos:
            print("[ERROR] No se pudieron cargar activos desde la BD. Abortando.")
            return

        # 3. Transformar/filtrar fills aplicando reglas de negocio
        fills_procesados = transformar_fills(raw_fills, mapa_activos)

        if not fills_procesados:
            print("\nNo hay operaciones válidas para insertar. Fin.")
            return

        # 4. Persistir en PostgreSQL con control de idempotencia
        print(f"\nInsertando {len(fills_procesados)} operaciones en asset_transactions...\n")
        insertados, omitidos = persistir_fills(db, fills_procesados)

    print(
        f"\n{'='*50}"
        f"\nPROCESO FINALIZADO"
        f"\n  Insertados  : {insertados}"
        f"\n  Duplicados  : {omitidos}"
        f"\n{'='*50}"
    )


if __name__ == "__main__":
    main()