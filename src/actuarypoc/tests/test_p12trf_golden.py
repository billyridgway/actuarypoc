from __future__ import annotations

"""Golden-test harness for the P12TRF term product.

For now this exercises the ProjectionEngine over the bundled
policies_p12trf.csv sample policies and asserts basic structural
properties of the output (lengths, non-empty series, etc.).

As actuarial expectations firm up, this file is the place to add
true "golden" checks for:

- cash value / reserve paths
- death benefit patterns
- premium present values / NPV
- lapse behaviour

The goal is that, over time, P12TRF behaviour is locked in here in a
way an actuary can inspect and trust.
"""

from pathlib import Path
import json
import math
import unittest

from actuarypoc.connectors.base import CSVConnector
from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.projection.engine import ProjectionEngine


# Base is the actuarypoc package root: src/actuarypoc
BASE = Path(__file__).resolve().parents[1]
SAMPLE_POLICIES = BASE / "sample_data" / "policies_p12trf.csv"
P12TRF_DSL = BASE / "dsl" / "examples" / "p12trf_term.yaml"
GOLDEN_DIR = BASE / "tests" / "golden" / "p12trf"


class TestP12TRFGolden(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.formula = load_formula(str(P12TRF_DSL))
        cls.engine = ProjectionEngine(cls.formula)
        cls.policies = list(CSVConnector(str(SAMPLE_POLICIES)).fetch())

    def test_sample_policies_available(self) -> None:
        # Sanity check that we have at least a few policies to project.
        self.assertGreaterEqual(len(self.policies), 1)

    def test_policies_project_structurally(self) -> None:
        # For now, assert that each sample policy can be projected for 40 years
        # and that the engine returns consistent series lengths, plus a set of
        # basic invariants that catch many engine mistakes.
        horizon = 40
        for rec in self.policies:
            with self.subTest(policy_number=rec.get("policy_number")):
                result = self.engine.project(rec, horizon=horizon)
                self.assertEqual(len(result.years), horizon)
                self.assertEqual(len(result.cash_values), horizon)
                self.assertEqual(len(result.death_benefits), horizon)

                if result.expected_premiums is not None:
                    self.assertEqual(len(result.expected_premiums), horizon)
                if result.expected_claims is not None:
                    self.assertEqual(len(result.expected_claims), horizon)
                if result.mortality_rates is not None:
                    self.assertEqual(len(result.mortality_rates), horizon)
                if result.survival_probabilities is not None:
                    self.assertEqual(len(result.survival_probabilities), horizon)

                # Invariants: non-negativity where expected.
                self.assertTrue(all(v >= 0 for v in result.cash_values))
                self.assertTrue(all(v >= 0 for v in result.death_benefits))

                # Mortality rates must be between 0 and 1.
                if result.mortality_rates is not None:
                    self.assertTrue(
                        all(0.0 <= v <= 1.0 for v in result.mortality_rates),
                        "mortality_rates outside [0,1]",
                    )

                # Survival probabilities: 0..1 and monotone non-increasing.
                if result.survival_probabilities is not None:
                    probs = result.survival_probabilities
                    self.assertTrue(all(0.0 <= v <= 1.0 for v in probs))
                    self.assertTrue(
                        all(probs[i + 1] <= probs[i] + 1e-12 for i in range(len(probs) - 1)),
                        "survival probabilities not monotone non-increasing",
                    )

                # No NaN / inf in any numeric sequences we have.
                numeric_seqs = [
                    ("cash_values", result.cash_values),
                    ("death_benefits", result.death_benefits),
                    ("expected_premiums", result.expected_premiums or []),
                    ("expected_claims", result.expected_claims or []),
                    ("pv_premiums", result.pv_premiums or []),
                    ("pv_claims", result.pv_claims or []),
                    ("pv_reserves", result.pv_reserves or []),
                ]
                for name, seq in numeric_seqs:
                    for v in seq:
                        self.assertTrue(math.isfinite(v), f"{name} contains non-finite value")

                # Premium PVs should be >= 0 when present.
                if result.pv_premiums is not None:
                    self.assertTrue(all(v >= 0 for v in result.pv_premiums))

                # TODO: as P12TRF behaviour is nailed down, replace or augment
                # these invariants with true golden values (e.g. specific
                # reserves, PVs, or benefit patterns) per policy.

    def test_golden_case_scaffolding(self) -> None:
        """Scaffolding for JSON-based golden tests.

        This does not assert numeric equality yet; it simply wires the
        loading and projection of any policy_XXX_expected.json files found
        under tests/golden/p12trf/ so that, once expected metrics are
        populated from an external actuarial source, we can start adding
        assertAlmostEqual checks here.
        """

        if not GOLDEN_DIR.exists():
            self.skipTest("No golden cases directory yet")

        policy_by_number = {p.get("policy_number"): p for p in self.policies}

        for expected_path in sorted(GOLDEN_DIR.glob("policy_*_expected.json")):
            with self.subTest(expected=str(expected_path)):
                data = json.loads(expected_path.read_text(encoding="utf-8"))
                policy_number = data.get("policy_number")
                horizon = int(data.get("horizon", 40))
                metrics = data.get("metrics", {}) or {}

                self.assertIn(policy_number, policy_by_number)
                rec = policy_by_number[policy_number]

                result = self.engine.project(rec, horizon=horizon)
                self.assertEqual(len(result.years), horizon)
                self.assertEqual(len(result.cash_values), horizon)
                self.assertEqual(len(result.death_benefits), horizon)

                # When metrics are eventually populated, this is where we will
                # add true golden checks, for example:
                #
                # if "cash_value_year_10" in metrics:
                #     self.assertAlmostEqual(
                #         result.cash_values[9],
                #         metrics["cash_value_year_10"],
                #         places=2,
                #     )
                #
                # For now, metrics is expected to be empty or partial, and we
                # intentionally do not assert on any numeric values.


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
