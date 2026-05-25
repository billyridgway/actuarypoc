from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from actuarypoc.dsl.policy_dsl import CreditRate, PolicyFormula
from actuarypoc.projection.mortality import Term23MortalitySurface


@dataclass
class ProjectionResult:
    years: List[int]
    # Interpreted as a simple theoretical reserve / account value for term:
    # grows with expected premiums, interest, and decrements for expected claims.
    cash_values: List[float]
    death_benefits: List[float]
    # Optional series of mortality rates (q_x) used in the projection, by duration.
    mortality_rates: Optional[List[float]] = None
    # Survival probability to the start of each year t (before decrement in year t).
    survival_probabilities: Optional[List[float]] = None
    # Expected values (per policy issued) in year t.
    expected_premiums: Optional[List[float]] = None
    expected_claims: Optional[List[float]] = None
    # Discounted present values (using either NF rate or interest_rate).
    pv_premiums: Optional[List[float]] = None
    pv_claims: Optional[List[float]] = None
    pv_reserves: Optional[List[float]] = None
    # Net level premium (per policy issued) derived from PV of benefits vs PV of
    # unit premiums using mortality + discount rate.
    net_level_premium: Optional[float] = None
    # Reserve track using the net level premium instead of the gross premium.
    nf_reserves: Optional[List[float]] = None
    pv_nf_reserves: Optional[List[float]] = None


class ProjectionEngine:
    def __init__(self, formula: PolicyFormula, mortality_surface: Optional[Term23MortalitySurface] = None) -> None:
        self.formula = formula
        self.mortality_surface = mortality_surface

    def project(self, policy_record: Dict[str, float | str], horizon: int = 20) -> ProjectionResult:
        # Map from generic PAS-style fields to the simple stub variables.
        # This keeps the engine usable both from the CLI and from connector outputs.
        raw_premium = policy_record.get("premium")
        if raw_premium is None:
            raw_premium = policy_record.get("premium_amount", 0)

        raw_rate = policy_record.get("interest_rate")
        if raw_rate is None:
            # Fallback for future integrations that might pass an `interest_rate_basis`
            raw_rate = policy_record.get("interest_rate_basis", 0.04)

        premium = float(raw_premium or 0)
        face_amount = float(policy_record.get("face_amount", 0))
        rate = float(raw_rate or 0.04)

        cash_values: List[float] = []
        death_benefits: List[float] = []
        mortality_rates: List[float] = []
        survival_probabilities: List[float] = []
        expected_premiums: List[float] = []
        expected_claims: List[float] = []
        pv_premiums: List[float] = []
        pv_claims: List[float] = []
        pv_reserves: List[float] = []

        # For net level premium calculation we also track PV of benefits and
        # PV of unit premiums (per policy issued) under the same mortality and
        # discount-rate basis.
        pv_benefits_basis: float = 0.0
        pv_prem_basis: float = 0.0

        # For this POC, we treat cash_values as a simple theoretical reserve that
        # evolves with expected premiums, interest, and expected claims.
        reserve = 0.0

        # Crude Term23 mortality usage for POC: derive a single age/gender/class view
        # from the policy_record and pull q_x per duration when a Term23 surface exists.
        gender = str(policy_record.get("gender", "Male"))
        smoker_class = str(policy_record.get("smoker_class", "Nontobacco"))
        risk_class = str(policy_record.get("risk_class", "Standard"))

        # Face banding per memo: 1: 200k-999,999; 2: 1M-2,999,999; 3: 3M-50M
        try:
            fa = float(face_amount)
        except (TypeError, ValueError):
            fa = 0.0
        if fa >= 3_000_000:
            face_band = 3
        elif fa >= 1_000_000:
            face_band = 2
        else:
            face_band = 1

        # In real data we would use issue_age; for the POC we default to 35 if missing,
        # which matches the sample Term23 table slice.
        try:
            issue_age = int(policy_record.get("issue_age", 35))
        except (TypeError, ValueError):
            issue_age = 35

        # Discount rate for PVs: prefer nonforfeiture rate if available on the
        # mortality surface; otherwise fall back to the illustration rate.
        nf_rate = getattr(self.mortality_surface, "nonforfeiture_rate", None)
        discount_rate = float(nf_rate) if nf_rate is not None else rate

        survival = 1.0

        for year in range(1, horizon + 1):
            # Survival prob to start of year t
            survival_probabilities.append(round(survival, 10))

            # Look up mortality for this duration if we have a surface
            qx = None
            if self.mortality_surface is not None:
                qx = self.mortality_surface.q_2017_cso(
                    gender=gender,
                    smoker_class=smoker_class,
                    risk_class=risk_class,
                    face_band=face_band,
                    issue_age=issue_age,
                    duration=year,
                )
            qx_val = float(qx) if qx is not None else 0.0
            mortality_rates.append(qx_val)

            # Expected cash flows per policy issued in policy year t
            exp_premium = premium * survival
            exp_claim = face_amount * survival * qx_val
            expected_premiums.append(round(exp_premium, 6))
            expected_claims.append(round(exp_claim, 6))

            # Simple reserve / cash value evolution: previous reserve grows with
            # interest, then we add expected premium and subtract expected claim.
            reserve = reserve * (1 + rate) + exp_premium - exp_claim
            cash_values.append(round(reserve, 2))

            # Discounted values to time 0
            disc = (1.0 + discount_rate) ** (-year)
            pv_premiums.append(round(exp_premium * disc, 6))
            pv_claims.append(round(exp_claim * disc, 6))
            pv_reserves.append(round(reserve * disc, 6))

            # Basis for net level premium: assume a unit premium per policy
            # issued, payable while in force, and equate PV(benefits) with
            # NLP * PV(unit premiums).
            pv_benefits_basis += face_amount * survival * qx_val * disc
            pv_prem_basis += survival * disc

            # For reporting, keep the same illustrative "death benefit" view as
            # before – level face plus a small function of the reserve.
            death_benefits.append(round(face_amount + 0.05 * reserve, 2))

            # Update survival for next year
            survival *= (1.0 - qx_val)

        # Solve net level premium per policy issued.
        net_level_premium: Optional[float]
        if pv_prem_basis > 0:
            net_level_premium = pv_benefits_basis / pv_prem_basis
        else:
            net_level_premium = None

        # Build a separate NF reserve track using the net level premium instead
        # of the gross premium, under the same mortality / interest basis.
        nf_reserves: List[float] = []
        pv_nf_reserves: List[float] = []
        nf_reserve = 0.0
        for year, (surv, qx_val) in enumerate(zip(survival_probabilities, mortality_rates), start=1):
            if net_level_premium is None:
                break
            exp_nf_prem = net_level_premium * surv
            exp_claim = face_amount * surv * qx_val
            nf_reserve = nf_reserve * (1 + rate) + exp_nf_prem - exp_claim
            nf_reserves.append(round(nf_reserve, 2))
            disc = (1.0 + discount_rate) ** (-year)
            pv_nf_reserves.append(round(nf_reserve * disc, 6))

        return ProjectionResult(
            years=list(range(1, horizon + 1)),
            cash_values=cash_values,
            death_benefits=death_benefits,
            mortality_rates=mortality_rates or None,
            survival_probabilities=survival_probabilities or None,
            expected_premiums=expected_premiums or None,
            expected_claims=expected_claims or None,
            pv_premiums=pv_premiums or None,
            pv_claims=pv_claims or None,
            pv_reserves=pv_reserves or None,
            net_level_premium=net_level_premium,
            nf_reserves=nf_reserves or None,
            pv_nf_reserves=pv_nf_reserves or None,
        )
