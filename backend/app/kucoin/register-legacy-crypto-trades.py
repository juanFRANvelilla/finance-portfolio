import ccxt
import os
import pandas as pd
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv


def extraer_historial_por_semanas():
    load_dotenv()

    exchange = ccxt.kucoin({
        'apiKey': os.getenv('KUCOIN_API_KEY'),
        'secret': os.getenv('KUCOIN_SECRET'),
        'password': os.getenv('KUCOIN_PASSPHRASE'),
        'enableRateLimit': True,
    })

    print("Iniciando escaneo de ejecuciones (Fills) semana a semana...")

    # Rango de fechas
    start_date = datetime(2025, 11, 1)
    end_date = datetime.now()

    all_fills = []
    current_start = start_date

    while current_start < end_date:
        # Ventanas estrictas de 6 días para no chocar con el límite de KuCoin
        current_end = current_start + timedelta(days=6)
        if current_end > end_date:
            current_end = end_date

        start_ms = int(current_start.timestamp() * 1000)
        end_ms = int(current_end.timestamp() * 1000)

        print(f"Consultando ventana: {current_start.strftime('%Y-%m-%d')} a {current_end.strftime('%Y-%m-%d')}...")

        try:
            # private_get_fills devuelve los trades ejecutados reales
            response = exchange.private_get_fills({
                'startAt': start_ms,
                'endAt': end_ms,
                'pageSize': 100  # Si haces más de 100 trades a la semana, habría que paginar dentro del bucle
            })

            items = response.get('data', {}).get('items', [])
            if items:
                all_fills.extend(items)
                print(f"  -> ¡Encontrados {len(items)} trades!")

        except Exception as e:
            print(f"Error en ventana {current_start.strftime('%Y-%m-%d')}: {e}")

        # Avanzar al siguiente bloque y respetar los límites de peticiones de la API
        current_start = current_end + timedelta(seconds=1)
        time.sleep(0.3)

    if not all_fills:
        print("\nNo se encontraron operaciones en Spot tras escanear todo el periodo.")
        print(
            "IMPORTANTE: Si no sale nada aquí, significa que tus compras se hicieron mediante la opción 'Convertir' (OTC) y no como órdenes de mercado.")
        return

    # Procesar y limpiar datos
    datos = []
    for f in all_fills:
        datos.append({
            'Fecha': pd.to_datetime(int(f.get('createdAt', 0)), unit='ms'),
            'Par': f.get('symbol', ''),
            'Tipo': f.get('side', '').upper(),
            'Precio Ejecución': float(f.get('price', 0)),
            'Cantidad Comprada': float(f.get('size', 0)),
            'Total Gastado': float(f.get('funds', 0)),
            'Fee Pagado': float(f.get('fee', 0)),
            'Moneda Fee': f.get('feeCurrency', '')
        })

    # Guardar en Excel
    df = pd.DataFrame(datos).sort_values(by='Fecha')
    archivo_salida = 'KuCoin_Fills_Completos.xlsx'
    df.to_excel(archivo_salida, index=False)

    print(f"\n¡Éxito! Se han exportado {len(df)} ejecuciones reales a '{archivo_salida}'")

    # Resumen rápido por consola de lo gastado
    print("\n=== RESUMEN DE GASTO EN FIAT/STABLECOIN ===")
    compras = df[df['Tipo'] == 'BUY']
    for par, group in compras.groupby('Par'):
        gastado = group['Total Gastado'].sum()
        if '-' in par:
            quote = par.split('-')[1]
        else:
            quote = par[-3:]  # Fallback por si el formato viene sin guion
        print(f"Par {par}: {gastado:.2f} {quote}")


if __name__ == '__main__':
    extraer_historial_por_semanas()