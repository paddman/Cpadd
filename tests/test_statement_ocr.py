import unittest

from app.services.statement_ocr import normalize_date, parse_statement_rules


SAMPLE = """
CARD TYPE KBANK PLUSTINUM 4921 41XX XXXX 8406
PREVIOUS BALANCE 3,373.20
28/06/26 28/06/26 PAYMENT - OTHER BANK -3,374.00
16/07/26 17/07/26 CHULABHORN ROYAL ACADEMY BANGKOK 850.00
25/07/26 25/07/26 XIAOMI-C.(WESTGATE)-BANGY : 03/10 880.00
25/07/26 25/07/26 PWB-CPN WESTGATE : 05/10 969.10
***** TOTAL BALANCE ***** 2,698.30
"""


class StatementRuleParserTests(unittest.TestCase):
    def test_short_year_date(self):
        self.assertEqual(normalize_date("25/07/26"), "2026-07-25")

    def test_buddhist_year_date(self):
        self.assertEqual(normalize_date("24/07/2569"), "2026-07-24")

    def test_kbank_statement(self):
        result = parse_statement_rules(SAMPLE)
        self.assertEqual(len(result["transactions"]), 4)
        self.assertEqual(result["statement"]["previous_balance"], 3373.20)
        self.assertEqual(result["statement"]["total_balance"], 2698.30)

        payment = result["transactions"][0]
        self.assertEqual(payment["entry_type"], "transfer")
        self.assertEqual(payment["amount"], 3374.00)

        xiaomi = result["transactions"][2]
        self.assertEqual(xiaomi["installment_current"], 3)
        self.assertEqual(xiaomi["installment_total"], 10)
        self.assertEqual(xiaomi["transaction_date"], "2026-07-25")


if __name__ == "__main__":
    unittest.main()
