"""Parser de transferencias MyInvestor."""

import unittest

from app.myinvestor.transfers.parse_transfer import (
    parse_myinvestor_transfer,
    diagnose_transfer_parse,
)

SAMPLE_BODY = """
DETALLE OPERACIÓN
TRANSFERENCIA INMEDIATA   0f5fb1ddf1ce44c4a57c5acb1a634591   MYINVESTOR
Fecha Operación   Fecha Valor
28/09/2026   28/09/2026
Importe Bruto   Cuenta
800.00 EUR   XXXX-XXXX-XX-XXXXXX1411
Importe Neto (1)
800.00 EUR
(1) El Importe Neto ha sido anotado en su cuenta en la fecha indicada.
"""

SAMPLE_SUBJECT = (
    "** MYINVESTOR ** TRANSFERENCIA INMEDIATA XXXXXX7335#Fecha:28-09-2026#TRANSFERENCIA INMEDIATA# 800.00"
)


class ParseMyInvestorTransferTest(unittest.TestCase):
    def test_parses_reference_date_and_amount(self) -> None:
        self.assertEqual(diagnose_transfer_parse(SAMPLE_SUBJECT, SAMPLE_BODY), [])
        transfer = parse_myinvestor_transfer(SAMPLE_SUBJECT, SAMPLE_BODY)
        self.assertIsNotNone(transfer)
        assert transfer is not None
        self.assertEqual(transfer.reference, "0f5fb1ddf1ce44c4a57c5acb1a634591")
        self.assertEqual(transfer.source_reference, "myinvestor:transfer:0f5fb1ddf1ce44c4a57c5acb1a634591")
        self.assertEqual(str(transfer.flow_date), "2026-09-28")
        self.assertEqual(float(transfer.amount), 800.0)
        self.assertEqual(transfer.currency, "EUR")

    def test_thousands_separator(self) -> None:
        body = SAMPLE_BODY.replace("800.00 EUR", "1,000.00 EUR", 2)
        subject = SAMPLE_SUBJECT.replace("800.00", "1,000.00")
        transfer = parse_myinvestor_transfer(subject, body)
        self.assertIsNotNone(transfer)
        assert transfer is not None
        self.assertEqual(float(transfer.amount), 1000.0)


if __name__ == "__main__":
    unittest.main()
