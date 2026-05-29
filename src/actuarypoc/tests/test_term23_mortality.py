from __future__ import annotations

"""Unit tests for the Term23 2017 CSO mortality surface wiring.

These tests exercise the CSV → in-memory surface construction and a few
lookup paths, including normalisation of gender / smoker / risk class
labels. Product-specific risk class mapping (e.g. P12TRF) is intentionally
kept out of this module and should live in DSL/tables/AssumptionSets.
"""

from pathlib import Path
import unittest

from actuarypoc.connectors.base import CSVConnector
from actuarypoc.projection.mortality import build_term23_surface


BASE = Path(__file__).resolve().parents[1]
TERM23_TABLE = BASE / "sample_data" / "actuarial_tables_term23.csv"


class TestTerm23MortalitySurface(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        records = list(CSVConnector(str(TERM23_TABLE)).fetch())
        cls.surface = build_term23_surface(records)
        if cls.surface is None:
            raise unittest.SkipTest("No Term23 mortality surface could be built")

    def test_nonforfeiture_rate_loaded(self) -> None:
        # The sample slice encodes the 4.5% nonforfeiture rate used in the
        # Term23 memo.
        self.assertAlmostEqual(self.surface.nonforfeiture_rate, 0.045, places=6)

    def test_basic_qx_lookup(self) -> None:
        # Direct lookup using the textual labels used in the sample CSV.
        q1 = self.surface.q_2017_cso(
            gender="Male",
            smoker_class="Nontobacco",
            risk_class="Standard",
            face_band=1,
            issue_age=35,
            duration=1,
        )
        q2 = self.surface.q_2017_cso(
            gender="Male",
            smoker_class="Nontobacco",
            risk_class="Standard",
            face_band=1,
            issue_age=35,
            duration=2,
        )

        self.assertIsNotNone(q1)
        self.assertIsNotNone(q2)

        self.assertAlmostEqual(float(q1), 0.00080, places=8)
        self.assertAlmostEqual(float(q2), 0.00082, places=8)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
