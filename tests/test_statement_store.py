import os
import tempfile
import unittest
from pathlib import Path

from app.config import get_settings
from app.database import init_db
from app.services.statement_store import (
    commit_statement_import,
    get_statement_import,
    save_statement_preview,
)


class StatementStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = str(Path(self.temp_dir.name) / "test.db")
        get_settings.cache_clear()
        init_db()

    def tearDown(self):
        get_settings.cache_clear()
        os.environ.pop("DATABASE_PATH", None)
        self.temp_dir.cleanup()

    def test_preview_and_commit(self):
        analysis = {
            "statement": {"bank": "KBank", "currency": "THB", "total_balance": 880.0},
            "transactions": [
                {
                    "transaction_date": "2026-07-25",
                    "posting_date": "2026-07-25",
                    "description": "XIAOMI : 03/10",
                    "amount": 880.0,
                    "direction": "debit",
                    "entry_type": "expense",
                    "category": "อุปกรณ์ไอที",
                    "merchant": "XIAOMI",
                    "installment_current": 3,
                    "installment_total": 10,
                    "confidence": 0.9,
                }
            ],
            "warnings": [],
            "parser": "rules",
            "model": None,
            "ocr_engine": "Tesseract (tha+eng)",
            "extraction_method": "tesseract",
            "page_count": 1,
            "raw_text": "sample",
        }
        preview = save_statement_preview(
            filename="statement.pdf",
            file_hash="abc123",
            mime_type="application/pdf",
            scope="personal",
            account="KBank 8406",
            analysis=analysis,
        )
        self.assertEqual(preview["transaction_count"], 1)

        result = commit_statement_import(
            preview["id"],
            selected_indices=[0],
            scope=None,
            account=None,
        )
        self.assertEqual(result["imported_count"], 1)
        detail = get_statement_import(preview["id"])
        self.assertEqual(detail["status"], "imported")
        self.assertEqual(detail["imported_count"], 1)


if __name__ == "__main__":
    unittest.main()
