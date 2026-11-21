import io
import unittest
import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.monthly_category_expense import MonthlyCategoryExpense
from app.services.expenses_service import (
    categorize_concept,
    get_monthly_expenses,
    import_expenses_for_month,
    parse_and_aggregate_excels_multimonth,
)


def _generate_mock_excel(data: list[dict], is_account: bool) -> bytes:
    cols = (
        ["FECHA OPERACIÓN", "FECHA VALOR", "CONCEPTO", "IMPORTE EUR", "SALDO"]
        if is_account
        else ["FECHA OPERACIÓN", "CONCEPTO", "IMPORTE EUR"]
    )
    df = pd.DataFrame(data, columns=cols)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        preamble = pd.DataFrame([[""] * len(cols)] * 5)
        preamble.to_excel(writer, header=False, index=False)
        df.to_excel(writer, startrow=6, index=False)
    return buf.getvalue()


def get_test_excel_bytes() -> tuple[bytes, bytes]:
    """Genera extractos Excel sintéticos en memoria para tests herméticos sin acceder a disco."""
    acc_data = [
        {"FECHA OPERACIÓN": "30/10/2026", "FECHA VALOR": "30/10/2026", "CONCEPTO": "Recibo Paypal Europe S.a.r.l. Nº Recibo 0049 Bblhzfx", "IMPORTE EUR": -15.85, "SALDO": 3499.04},
        {"FECHA OPERACIÓN": "26/10/2026", "FECHA VALOR": "26/10/2026", "CONCEPTO": "Recibo Paypal Europe S.a.r.l. Nº Recibo 0049 Bblhrhz", "IMPORTE EUR": -17.99, "SALDO": 10.47},
        {"FECHA OPERACIÓN": "21/10/2026", "FECHA VALOR": "21/10/2026", "CONCEPTO": "Recibo Paypal Europe S.a.r.l. Nº Recibo 0049 Bblhmwb", "IMPORTE EUR": -65.24, "SALDO": 101.26},
        {"FECHA OPERACIÓN": "20/10/2026", "FECHA VALOR": "20/10/2026", "CONCEPTO": "Recibo Paypal Europe S.a.r.l. Nº Recibo 0049 Bblhlwg", "IMPORTE EUR": -6.15, "SALDO": 172.0},
        {"FECHA OPERACIÓN": "19/10/2026", "FECHA VALOR": "19/10/2026", "CONCEPTO": "Recibo Paypal Europe S.a.r.l. Nº Recibo 0049 Bblhkyf", "IMPORTE EUR": -210.12, "SALDO": 178.15},
        {"FECHA OPERACIÓN": "01/10/2026", "FECHA VALOR": "01/10/2026", "CONCEPTO": "Recibo Paypal Europe S.a.r.l. Nº Recibo 0049 Bblgkyd", "IMPORTE EUR": -2.99, "SALDO": 4085.33},
        {"FECHA OPERACIÓN": "02/10/2026", "FECHA VALOR": "02/10/2026", "CONCEPTO": "Renting Tec", "IMPORTE EUR": -24.99, "SALDO": 4000.0},
        {"FECHA OPERACIÓN": "02/10/2026", "FECHA VALOR": "02/10/2026", "CONCEPTO": "Bonificacion De Campaña", "IMPORTE EUR": 24.99, "SALDO": 4000.0},
        {"FECHA OPERACIÓN": "26/10/2026", "FECHA VALOR": "26/10/2026", "CONCEPTO": "Compra Bizum Kinepolis Paterna S A 26/10/2026", "IMPORTE EUR": -4.0, "SALDO": 4000.0},
        {"FECHA OPERACIÓN": "16/10/2026", "FECHA VALOR": "16/10/2026", "CONCEPTO": "C.d.m. Gran Via 16/10/2026", "IMPORTE EUR": -51.5, "SALDO": 4000.0},
        {"FECHA OPERACIÓN": "02/10/2026", "FECHA VALOR": "02/10/2026", "CONCEPTO": "Retirada De Efectivo En Cajero Automatico 0049", "IMPORTE EUR": -20.0, "SALDO": 4000.0},
        {"FECHA OPERACIÓN": "05/10/2026", "FECHA VALOR": "05/10/2026", "CONCEPTO": "Recibo Fundacion Unicef Comite Espanol", "IMPORTE EUR": -3.0, "SALDO": 4000.0},
        {"FECHA OPERACIÓN": "05/10/2026", "FECHA VALOR": "05/10/2026", "CONCEPTO": "Recibo Fit Zea Sl - Fitness Park Delicias", "IMPORTE EUR": -25.0, "SALDO": 4000.0},
        {"FECHA OPERACIÓN": "10/10/2026", "FECHA VALOR": "10/10/2026", "CONCEPTO": "Bizum A Favor De Carlos Velilla Guerrero Concepto: Cena", "IMPORTE EUR": -29.35, "SALDO": 4000.0},
        {"FECHA OPERACIÓN": "11/10/2026", "FECHA VALOR": "11/10/2026", "CONCEPTO": "Bizum De Amigo Reembolso Cena", "IMPORTE EUR": 8.05, "SALDO": 4000.0},
    ]

    card_data = [
        {"FECHA OPERACIÓN": "27/10/2026", "CONCEPTO": "Bonarea Car Pay", "IMPORTE EUR": -55.0},
        {"FECHA OPERACIÓN": "06/10/2026", "CONCEPTO": "Bonarea Car Pay", "IMPORTE EUR": -60.0},
        {"FECHA OPERACIÓN": "06/10/2026", "CONCEPTO": "Mercadona Avda.", "IMPORTE EUR": -47.55},
        {"FECHA OPERACIÓN": "20/10/2026", "CONCEPTO": "Mercadona Avda.", "IMPORTE EUR": -72.0},
        {"FECHA OPERACIÓN": "25/10/2026", "CONCEPTO": "John Pye And Sons Limi", "IMPORTE EUR": -84.7},
        {"FECHA OPERACIÓN": "04/10/2026", "CONCEPTO": "John Pye And Sons Limi", "IMPORTE EUR": -159.4},
        {"FECHA OPERACIÓN": "05/10/2026", "CONCEPTO": "Ayuntamiento De", "IMPORTE EUR": -18.0},
        {"FECHA OPERACIÓN": "05/10/2026", "CONCEPTO": "Ayuntamiento De", "IMPORTE EUR": -18.0},
        {"FECHA OPERACIÓN": "27/10/2026", "CONCEPTO": "Bar Restaurante", "IMPORTE EUR": -6.9},
        {"FECHA OPERACIÓN": "25/10/2026", "CONCEPTO": "Bar Cuco", "IMPORTE EUR": -7.5},
        {"FECHA OPERACIÓN": "24/10/2026", "CONCEPTO": "Slavquima", "IMPORTE EUR": -4.0},
        {"FECHA OPERACIÓN": "24/10/2026", "CONCEPTO": "Trekkinn", "IMPORTE EUR": -25.97},
        {"FECHA OPERACIÓN": "24/10/2026", "CONCEPTO": "Loom", "IMPORTE EUR": -17.0},
        {"FECHA OPERACIÓN": "24/10/2026", "CONCEPTO": "Bicicletas Zara", "IMPORTE EUR": -11.0},
        {"FECHA OPERACIÓN": "24/10/2026", "CONCEPTO": "Real Zaragoza C", "IMPORTE EUR": -17.0},
        {"FECHA OPERACIÓN": "24/10/2026", "CONCEPTO": "Cursor, Ai Powered Ide", "IMPORTE EUR": -23.72},
        {"FECHA OPERACIÓN": "24/10/2026", "CONCEPTO": "Sweets And Game", "IMPORTE EUR": -8.27},
        {"FECHA OPERACIÓN": "15/10/2026", "CONCEPTO": "Tribu", "IMPORTE EUR": -59.7},
        {"FECHA OPERACIÓN": "10/10/2026", "CONCEPTO": "Gentlebar", "IMPORTE EUR": -53.1},
        {"FECHA OPERACIÓN": "08/10/2026", "CONCEPTO": "Koi Asian Zarag", "IMPORTE EUR": -61.95},
        {"FECHA OPERACIÓN": "02/10/2026", "CONCEPTO": "Kinepolis", "IMPORTE EUR": -12.5},
        {"FECHA OPERACIÓN": "01/10/2026", "CONCEPTO": "Bar Arqueros", "IMPORTE EUR": -97.4},
    ]

    return _generate_mock_excel(acc_data, True), _generate_mock_excel(card_data, False)


class TestExpensesService(unittest.TestCase):
    def test_categorize_concept(self):
        self.assertEqual(categorize_concept("Mercadona Avda."), "mercadona")
        self.assertEqual(categorize_concept("Bonarea Car Pay"), "bonarea")
        self.assertEqual(categorize_concept("Bar Restaurante"), "restauracion_bares")
        self.assertEqual(categorize_concept("Gentlebar"), "restauracion_bares")
        self.assertEqual(categorize_concept("Bicicletas Zara"), "transporte_otros")
        self.assertEqual(categorize_concept("Kinepolis Paterna"), "ocio_deportes")
        self.assertEqual(categorize_concept("Cursor, Ai Powered Ide"), "suscripciones_fijas")
        self.assertEqual(categorize_concept("Ayuntamiento De Zaragoza"), "ayuntamiento_de")
        self.assertEqual(categorize_concept("Retirada De Efectivo En Cajero"), "cajero_efectivo")
        self.assertEqual(categorize_concept("Recibo Paypal Europe"), "paypal")
        self.assertEqual(categorize_concept("John Pye And Sons"), "john_pye")
        self.assertEqual(categorize_concept("Jhon Pye"), "john_pye")

    def test_batch_import_two_excels_together(self):
        """Verifica que subir Cuenta Corriente y Tarjeta de Crédito juntos procesa ambos ficheros consolidándolos."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()

        acc_bytes, card_bytes = get_test_excel_bytes()

        # 1. Subir ambos archivos a la vez
        res = import_expenses_for_month(
            db,
            [("acc.xls", acc_bytes), ("card.xls", card_bytes)],
            2026,
            10,
        )

        self.assertGreater(res.total_amount, 0)
        self.assertTrue(res.has_expenses)
        self.assertIn("10/2026", res.imported_months)
        self.assertIn("Cuenta Corriente", res.imported_sources)
        self.assertIn("Tarjeta de Crédito", res.imported_sources)

        cat_map = {c.category: c.amount for c in res.categories}
        self.assertIn("mercadona", cat_map)
        self.assertIn("bonarea", cat_map)
        self.assertIn("john_pye", cat_map)
        self.assertIn("paypal", cat_map)
        self.assertIn("ayuntamiento_de", cat_map)

        # Verificar detalle expandible de transacciones (items)
        ayto = next(c for c in res.categories if c.category == "ayuntamiento_de")
        self.assertEqual(len(ayto.items), 1)
        self.assertEqual(ayto.items[0].concept, "Ayuntamiento De")
        self.assertEqual(ayto.items[0].count, 2)

        jp = next(c for c in res.categories if c.category == "john_pye")
        self.assertEqual(len(jp.items), 1)
        self.assertEqual(jp.items[0].count, 2)

        pp = next(c for c in res.categories if c.category == "paypal")
        self.assertEqual(len(pp.items), 6)
        self.assertTrue(pp.items[0].concept.startswith("Pago PayPal"))

        # 2. Si más adelante se vuelve a subir un excel que contiene el mes 10/2026, ese mes se omite
        res_subsequent = import_expenses_for_month(
            db,
            [("acc.xls", acc_bytes)],
            2026,
            10,
        )
        self.assertIn("10/2026", res_subsequent.skipped_months)
        self.assertEqual(res_subsequent.total_amount, res.total_amount)

        db.close()

    def test_sequential_upload_second_file_is_completely_ignored(self):
        """Verifica que si se sube un fichero por separado y luego otro, el segundo se ignora por completo para ese mes."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()

        acc_bytes, card_bytes = get_test_excel_bytes()

        # 1. Subir solo la cuenta corriente
        res1 = import_expenses_for_month(db, [("acc.xls", acc_bytes)], 2026, 10)
        self.assertGreater(res1.total_amount, 0)
        self.assertIn("10/2026", res1.imported_months)
        first_total = res1.total_amount

        # 2. Subir posteriormente la tarjeta de crédito por separado para el mismo mes
        res2 = import_expenses_for_month(db, [("card.xls", card_bytes)], 2026, 10)
        # Debe omitir el mes 10/2026 y no tocar los datos existentes
        self.assertIn("10/2026", res2.skipped_months)
        self.assertEqual(res2.total_amount, first_total)
        self.assertEqual(res2.imported_sources, ["Cuenta Corriente"])

        db.close()


if __name__ == "__main__":
    unittest.main()
