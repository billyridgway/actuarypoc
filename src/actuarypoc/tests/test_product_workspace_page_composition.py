from __future__ import annotations

from pathlib import Path


def test_product_workspace_page_keeps_normal_flow_on_one_primary_surface() -> None:
    source = Path(__file__).resolve().parents[3] / "web" / "ProductWorkspacePage.tsx"
    text = source.read_text()
    advanced_gate = text.index("{showAdvancedDebug && (")

    assert "Primary Workspace Summary" in text
    assert "Evidence and Provenance" in text
    assert "Readiness, Gaps, and Required Actions" in text
    assert "Single-page guided review surface" in text
    assert "showAdvancedDebug && (" in text

    # Legacy panels remain in the file for advanced/debug access, but the
    # normal path should not present them as the primary review surface.
    assert "Primary Workspace Summary" in text[:advanced_gate]
    assert "Draft illustration (product understanding only)" in text[advanced_gate:]
    assert "Mechanics explanation / order of operations" in text[advanced_gate:]
    assert "Uploaded documents" in text[advanced_gate:]
    assert "Projection vs blockers" in text
    assert "Server returned deterministic projection" in text
    assert "Server denied projection" in text
