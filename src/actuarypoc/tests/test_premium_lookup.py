from __future__ import annotations

"""Tests for the generic PremiumLookupService.

These tests exercise the CSV → in-memory PremiumTable construction and
lookup for a thin synthetic P12TRF grid. The goal is to validate the
lookup mechanics without baking any product-specific logic into Python:
the risk class labels and table shape are entirely driven by the CSV.
"""

from pathlib import Path
import unittest

from actuarypoc.connectors.base import CSVConnector
from actuarypoc.projection.premium import build_premium_table, PremiumLookupService


BASE = Path(__file__).resolve().parents[1]
PREMIUM_CSV = BASE / "sample_data" / "p12trf_premiums.synthetic.csv"


class TestPremiumLookupService(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        records = list(CSVConnector(str(PREMIUM_CSV)).fetch())
        table = build_premium_table(records)
        if table is None:
            raise unittest.SkipTest("No premium table could be built from sample data")
        cls.service = PremiumLookupService(table)

    def test_exact_match_for_sample_rows(self) -> None:
        # These expectations mirror the synthetic grid in
        # sample_data/p12trf_premiums.synthetic.csv. They are intentionally simple but
        # use realistic-looking inputs (issue age, gender, risk class,
        # face band, level period).

        prem_1 = self.service.premium_per_1000(
            issue_age=35,
            gender="M",
            risk_class="SUPER_PREFERRED_NON_TOBACCO",
            face_band=1,
            level_period=10,
        )
        self.assertIsNotNone(prem_1)
        self.assertAlmostEqual(float(prem_1), 0.80, places=8)

        prem_2 = self.service.premium_per_1000(
            issue_age=45,
            gender="F",
            risk_class="STANDARD_NON_TOBACCO",
            face_band=1,
            level_period=20,
        )
        self.assertIsNotNone(prem_2)
        self.assertAlmostEqual(float(prem_2), 1.10, places=8)

        prem_3 = self.service.premium_per_1000(
            issue_age=40,
            gender="M",
            risk_class="STANDARD_TOBACCO",
            face_band=1,
            level_period=30,
        )
        self.assertIsNotNone(prem_3)
        self.assertAlmostEqual(float(prem_3), 1.60, places=8)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
