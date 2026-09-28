"""Parser de confirmaciones MyInvestor, sin red ni base de datos."""

from __future__ import annotations

import unittest
from decimal import Decimal

from app.myinvestor.parse_trade import (
    amounts_for_asset_currency,
    parse_decimal_amount,
    parse_myinvestor_trade,
)
from app.services.myinvestor_sync_service import myinvestor_asset_lookup_keys

SAMPLE = """
CONFIRMACIÓN DE OPERACIÓN DE VALORES
DATOS PERSONALES
Titular JUAN FRANCISCO PEREZ VELILLA
Cta. asociada XXXX XXXX XXXX XXXX XXXX 7335 Divisa EUR
País Cuenta XXXX-XXXX-XX-XXXXXX7336
DETALLE OPERACIÓN
Mercado Valor
NYSE ALIBABA GROUP HOLDING SP ADR - BABA US
Código ISIN: US01609W1027
Operación Referencia Operación
COMPRA 157275659/1
Fecha Operación Fecha Valor Fecha y Hora Ejecución
24/09/2026 25/09/2026 24/09/2026 16:53:01
Número de títulos/Participaciones Precio Bruto Importe Bruto
4 110.250 USD 441.00 USD
Comisiones Gastos Tasas e Impuestos
3.40 USD 0.00 USD 0.00 USD
IVA
Operación exenta IVA . Art.20.1.18 Ley 37/1992
Retención Origen Retención Destino Importe Efectivo Neto (1)
0.00 USD 0.00 USD 444.40 USD 391.89 EUR
(1) El Importe Neto ha sido anotado en su cuenta corriente en la fecha indicada.
"""

SAMPLE_GOLD_EUR = """
CONFIRMACIÓN DE OPERACIÓN DE VALORES
DETALLE OPERACIÓN
Mercado Valor
PARIS    AMUNDI PHYSICAL GOLD ETC - GOLD FP
Código ISIN: FR0013416716
Operación Referencia Operación
COMPRA   157423889/1
Fecha Operación Fecha Valor Fecha y Hora Ejecución
28/09/2026   30/09/2026   28/09/2026 10:13:10
Número de títulos/Participaciones Precio Bruto Importe Bruto
3   144.550 EUR   433.65 EUR
Comisiones Gastos Tasas e Impuestos
1.00 EUR   0.00 EUR   0.00 EUR
Retención Origen Retención Destino Importe Efectivo Neto (1)
0.00 EUR   0.00 EUR   434.65 EUR
(1) El Importe Neto ha sido anotado en su cuenta corriente en la fecha indicada.
"""

SAMPLE_FUND_SUSCRIPCION = """
CONFIRMACIÓN DE OPERACIÓN DE VALORES
DETALLE OPERACIÓN
Mercado Valor
FONDOS EXTR   ISHARES EMERGING MARKETS INDEX S EUR ACC -
Código ISIN: IE000QAZP7L2
Operación Referencia Operación
SUSCRIPCION I.I.C.   156086978/336
Fecha Operación Fecha Valor
04/09/2026   08/09/2026
Número de títulos/Participaciones Precio Bruto Importe Bruto
28.97   13.8069 EUR   399.98 EUR
Comisiones Gastos Tasas e Impuestos
0.00 EUR   0.00 EUR   0.00 EUR
Retención Origen Retención Destino Importe Efectivo Neto (1) Tipo de Cambio
0.00 EUR   0.00 EUR   399.98 EUR   1.00 EUR
(1) El Importe Neto ha sido anotado en su cuenta corriente en la fecha indicada.
"""


class ParseMyInvestorTradeTest(unittest.TestCase):
    def test_compra_baba(self) -> None:
        trade = parse_myinvestor_trade(SAMPLE)
        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(trade.side, "COMPRA")
        self.assertEqual(trade.reference, "157275659/1")
        self.assertEqual(trade.ticker, "BABA")
        self.assertEqual(trade.isin, "US01609W1027")
        self.assertEqual(trade.market, "NYSE")
        self.assertEqual(trade.transaction_date.isoformat(), "2026-09-24")
        self.assertEqual(trade.execution_datetime.isoformat(), "2026-09-24T16:53:01")
        self.assertEqual(trade.asset_amount, Decimal("4"))
        self.assertEqual(trade.gross_price, Decimal("110.250"))
        self.assertEqual(trade.gross_amount, Decimal("441.00"))
        self.assertEqual(trade.trade_currency, "USD")
        self.assertEqual(trade.fee_amount, Decimal("3.40"))
        self.assertEqual(trade.net_trade_amount, Decimal("444.40"))
        self.assertEqual(trade.settlement_amount, Decimal("391.89"))
        self.assertEqual(trade.settlement_currency, "EUR")

    def test_usd_asset_keeps_gross_in_usd(self) -> None:
        trade = parse_myinvestor_trade(SAMPLE)
        assert trade is not None
        amounts = amounts_for_asset_currency(trade, "USD")
        self.assertIsNotNone(amounts)
        assert amounts is not None
        self.assertEqual(amounts.invested_amount, Decimal("444.40000000"))
        self.assertEqual(amounts.execution_price, Decimal("111.10000000"))
        self.assertEqual(amounts.fee_amount, Decimal("3.40000000"))
        self.assertEqual(amounts.asset_amount, Decimal("4"))

    def test_eur_asset_uses_implicit_fx_from_the_email(self) -> None:
        trade = parse_myinvestor_trade(SAMPLE)
        assert trade is not None
        amounts = amounts_for_asset_currency(trade, "EUR")
        self.assertIsNotNone(amounts)
        assert amounts is not None
        self.assertEqual(amounts.invested_amount, Decimal("391.89000000"))
        rate = Decimal("391.89") / Decimal("444.40")
        self.assertEqual(amounts.fee_amount, (Decimal("3.40") * rate).quantize(Decimal("0.00000001")))
        self.assertEqual(amounts.execution_price, (Decimal("391.89") / Decimal("4")).quantize(Decimal("0.00000001")))

    def test_venta_is_parsed_but_marked_as_sale(self) -> None:
        trade = parse_myinvestor_trade(SAMPLE.replace("COMPRA", "VENTA"))
        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(trade.side, "VENTA")

    def test_unrelated_email_is_ignored(self) -> None:
        self.assertIsNone(parse_myinvestor_trade("Su extracto mensual ya está disponible."))

    def test_european_thousands(self) -> None:
        self.assertEqual(parse_decimal_amount("1.234,56"), Decimal("1234.56"))
        self.assertEqual(parse_decimal_amount("110.250"), Decimal("110.250"))

    def test_gold_isin_aliases_to_yahoo_ticker(self) -> None:
        keys = myinvestor_asset_lookup_keys("FR0013416716", "FR0013416716")
        self.assertIn("FR0013416716.SG", keys)
        self.assertEqual(myinvestor_asset_lookup_keys("BABA", "US01609W1027"), ["BABA", "US01609W1027"])

    def test_gold_compra_eur_net_three_columns(self) -> None:
        trade = parse_myinvestor_trade(SAMPLE_GOLD_EUR)
        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(trade.side, "COMPRA")
        self.assertEqual(trade.ticker, "GOLD")
        self.assertEqual(trade.isin, "FR0013416716")
        self.assertEqual(trade.trade_currency, "EUR")
        self.assertEqual(trade.net_trade_amount, Decimal("434.65"))
        self.assertEqual(trade.settlement_amount, Decimal("434.65"))
        self.assertEqual(trade.execution_datetime.isoformat(), "2026-09-28T10:13:10")

    def test_gold_eur_invested_uses_net_including_commission(self) -> None:
        trade = parse_myinvestor_trade(SAMPLE_GOLD_EUR)
        assert trade is not None
        amounts = amounts_for_asset_currency(trade, "EUR")
        self.assertIsNotNone(amounts)
        assert amounts is not None
        self.assertEqual(amounts.invested_amount, Decimal("434.65000000"))
        self.assertEqual(amounts.execution_price, (Decimal("434.65") / Decimal("3")).quantize(Decimal("0.00000001")))

    def test_fund_suscripcion(self) -> None:
        trade = parse_myinvestor_trade(SAMPLE_FUND_SUSCRIPCION)
        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(trade.side, "SUSCRIPCION")
        self.assertEqual(trade.reference, "156086978/336")
        self.assertEqual(trade.isin, "IE000QAZP7L2")
        self.assertEqual(trade.ticker, "IE000QAZP7L2")
        self.assertEqual(trade.market, "FONDOS EXTR")
        self.assertEqual(trade.transaction_date.isoformat(), "2026-09-04")
        self.assertEqual(trade.execution_datetime.isoformat(), "2026-09-04T23:59:59")
        self.assertEqual(trade.gross_amount, Decimal("399.98"))
        self.assertEqual(trade.net_trade_amount, Decimal("399.98"))


if __name__ == "__main__":
    unittest.main()
