import unittest
from datetime import date

from app.services.finance import period_bounds


class PeriodBoundsTests(unittest.TestCase):
    def test_day(self):
        anchor = date(2026, 8, 4)
        self.assertEqual(period_bounds("day", anchor), (anchor, anchor))

    def test_week_starts_monday(self):
        start, end = period_bounds("week", date(2026, 8, 4))
        self.assertEqual(start, date(2026, 8, 3))
        self.assertEqual(end, date(2026, 8, 9))

    def test_month(self):
        start, end = period_bounds("month", date(2026, 2, 12))
        self.assertEqual(start, date(2026, 2, 1))
        self.assertEqual(end, date(2026, 2, 28))

    def test_year(self):
        start, end = period_bounds("year", date(2026, 8, 4))
        self.assertEqual(start, date(2026, 1, 1))
        self.assertEqual(end, date(2026, 12, 31))


if __name__ == "__main__":
    unittest.main()
