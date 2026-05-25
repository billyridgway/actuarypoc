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
import unittest

from actuarypoc.connectors.base import CSVConnector
from actuarypoc.dsl.policy_dsl import load_formula
from actuarypoc.projection.engine import ProjectionEngine


# Base is the actuarypoc package root: src/actuarypoc
BASE = Path(__file__).resolve().parents[1]
SAMPLE_POLICIES = BASE / "sample_data" / "policies_p12trf.csv"
P12TRF_DSL = BASE / "dsl" / "examples" / "p12trf_term.yaml"


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
        # and that the engine returns consistent series lengths.
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

                # TODO: as P12TRF behaviour is nailed down, replace or
                # augment these structural checks with true golden values
                # (e.g. specific reserves, PVs, or benefit patterns) per
                # policy.


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
