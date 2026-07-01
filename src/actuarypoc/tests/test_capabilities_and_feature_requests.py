from actuarypoc.domain.capabilities import CapabilityAssessmentItem, EngineCapability, get_ul_capabilities
from actuarypoc.domain.feature_requests import FeatureRequest
from actuarypoc.domain.life_product_models import BaseLifeProductModel


def test_ul_capabilities_catalog_non_empty() -> None:
    caps = get_ul_capabilities()
    assert any(c.product_type == "ul" for c in caps)
    ids = {c.capability_id for c in caps}
    assert "UL_CAP_COI_TABLE_AGE_GENDER_CLASS" in ids


def test_feature_request_dataclass_basic_fields() -> None:
    fr = FeatureRequest(
        product_code="UL-TEST",
        product_type="ul",
        capability_id="UL_CAP_COI_TABLE_AGE_GENDER_CLASS",
        title="Support full COI tables",
        description="Engine must support age/gender/class COI tables.",
        impact="high",
    )

    assert fr.product_code == "UL-TEST"
    assert fr.product_type == "ul"
    assert fr.capability_id.startswith("UL_CAP_")
    assert fr.status == "proposed"
    assert fr.created_at.endswith("Z")


def test_capability_assessment_item_shape() -> None:
    item = CapabilityAssessmentItem(
        capability_id="UL_CAP_SURRENDER_FIXED_SCHEDULE",
        name="UL surrender schedule",
        status="partial",
        impact="high",
        reason="Engine only supports flat surrender charge; product has banded schedule.",
        product_code="UL-TEST",
        product_type="ul",
        source_requirement_ids=["UL_SURRENDER_SCHEDULE"],
        source_requirement_text="Surrender charge follows filed schedule by duration.",
        source_document="ul-memo.pdf",
        source_reference="p.4",
    )

    assert item.status == "partial"
    assert item.product_code == "UL-TEST"
    assert item.product_type == "ul"
    assert "SURRENDER" in item.source_requirement_ids[0]


def test_base_life_product_model_is_compatible_with_feature_request_helpers() -> None:
    # Sanity check: the helper functions that accept BaseLifeProductModel
    # can rely on product_code and product_type being present.
    model = BaseLifeProductModel(product_code="UL-TEST", product_type="ul")
    assert model.product_code == "UL-TEST"
    assert model.product_type == "ul"
