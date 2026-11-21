import os
import unittest
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


def get_test_excel_paths():
    candidates = [
        "/Users/juanfran/Downloads/GASTOS/octubre",
        "/Users/juanfran/Downloads",
    ]
    for c in candidates:
        acc = os.path.join(c, "transactions_2026-10-30T18_35_01.460Z.xls")
        card = os.path.join(c, "export20261030.xls")
        if os.path.exists(acc) and os.path.exists(card):
            return acc, card
    raise FileNotFoundError("No se encontraron los ficheros de prueba en Downloads")


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

        acc_path, card_path = get_test_excel_paths()

        with open(acc_path, "rb") as f1, open(card_path, "rb") as f2:
            acc_bytes = f1.read()
            card_bytes = f2.read()

        # 1. Subir ambos archivos a la vez
        res = import_expenses_for_month(
            db,
            [("acc.xls", acc_bytes), ("card.xls", card_bytes)],
            2026,
            10,
        )

        self.assertEqual(res.total_amount, 1356.90)
        self.assertIn("10/2026", res.imported_months)
        self.assertIn("Cuenta Corriente", res.imported_sources)
        self.assertIn("Tarjeta de Crédito", res.imported_sources)

        cat_map = {c.category: c.amount for c in res.categories}
        self.assertEqual(cat_map["mercadona"], 119.55)
        self.assertEqual(cat_map["bonarea"], 115.00)
        self.assertEqual(cat_map["john_pye"], 244.10)
        self.assertEqual(cat_map["paypal"], 318.34)
        self.assertEqual(cat_map["ayuntamiento_de"], 36.00)
        self.assertEqual(cat_map["compras_shopping"], 52.57)
        self.assertEqual(cat_map["restauracion_bares"], 286.55)

        # Verificar detalle expandible de transacciones (items)
        ayto = next(c for c in res.categories if c.category == "ayuntamiento_de")
        self.assertEqual(len(ayto.items), 1)
        self.assertEqual(ayto.items[0].concept, "Ayuntamiento De")
        self.assertEqual(ayto.items[0].amount, 36.00)
        self.assertEqual(ayto.items[0].count, 2)

        jp = next(c for c in res.categories if c.category == "john_pye")
        self.assertEqual(len(jp.items), 1)
        self.assertEqual(jp.items[0].amount, 244.10)
        self.assertEqual(jp.items[0].count, 2)

        pp = next(c for c in res.categories if c.category == "paypal")
        self.assertEqual(len(pp.items), 6)
        self.assertEqual(pp.amount, 318.34)
        # El mayor de PayPal fue de 210.12 €
        self.assertEqual(pp.items[0].amount, 210.12)
        self.assertTrue(pp.items[0].concept.startswith("Pago PayPal"))

        # 2. Si más adelante se vuelve a subir un excel que contiene el mes 10/2026, ese mes se omite
        res_subsequent = import_expenses_for_month(
            db,
            [("acc.xls", acc_bytes)],
            2026,
            10,
        )
        self.assertIn("10/2026", res_subsequent.skipped_months)
        # El total sigue siendo el consolidado original sin machacar
        self.assertEqual(res_subsequent.total_amount, 1356.90)

        db.close()

    def test_sequential_upload_second_file_is_completely_ignored(self):
        """Verifica que si se sube un fichero por separado y luego otro, el segundo se ignora por completo para ese mes."""
        engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(bind=engine)
        TestSession = sessionmaker(bind=engine)
        db = TestSession()

        acc_path, card_path = get_test_excel_paths()

        with open(acc_path, "rb") as f1, open(card_path, "rb") as f2:
            acc_bytes = f1.read()
            card_bytes = f2.read()

        # 1. Subir solo la cuenta corriente
        res1 = import_expenses_for_month(db, [("acc.xls", acc_bytes)], 2026, 10)
        self.assertEqual(res1.total_amount, 443.14)
        self.assertIn("10/2026", res1.imported_months)

        # 2. Subir posteriormente la tarjeta de crédito por separado para el mismo mes
        res2 = import_expenses_for_month(db, [("card.xls", card_bytes)], 2026, 10)
        # Debe omitir el mes 10/2026 y no tocar los datos existentes
        self.assertIn("10/2026", res2.skipped_months)
        self.assertEqual(res2.total_amount, 443.14)
        self.assertEqual(res2.imported_sources, ["Cuenta Corriente"])

        db.close()


if __name__ == "__main__":
    unittest.main()
