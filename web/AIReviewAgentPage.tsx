import React, { useState } from "react";

export const AIReviewAgentPage: React.FC = () => {
  const [productCode, setProductCode] = useState<string>("");
  const [filingId, setFilingId] = useState<string>("");

  const [carrierName, setCarrierName] = useState<string>("");
  const [productName, setProductName] = useState<string>("");
  const [productType, setProductType] = useState<string>("");

  const [assumptionSetJson, setAssumptionSetJson] = useState<string | null>(null);
  const [pmrSummary, setPmrSummary] = useState<any | null>(null);
  const [pmrDecision, setPmrDecision] = useState<any | null>(null);

  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const normalisedCode = (productCode || "").trim();
  const normalisedFiling = (filingId || "").trim();

  const handleAutofillMetadata = async () => {
    if (!normalisedCode) {
      setError("Enter at least a product code hint before autofilling.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/product-review/metadata/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productCodeHint: normalisedCode,
          filingIdHint: normalisedFiling || undefined,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (data.carrier_name) setCarrierName(data.carrier_name);
      if (data.product_name) setProductName(data.product_name);
      if (data.product_code) setProductCode(data.product_code);
      if (data.product_type) setProductType(data.product_type);
      if (data.primary_filing_id) setFilingId(data.primary_filing_id);
    } catch (e: any) {
      setError(e?.message || "Failed to autofill metadata from filings.");
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateAssumptions = async () => {
    if (!normalisedCode) {
      setError("Enter a product code hint before generating assumptions.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/product-assumptions/ai-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productCodeHint: normalisedCode,
          filingIdHint: normalisedFiling || undefined,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setAssumptionSetJson(JSON.stringify(data.assumptionSet, null, 2));
    } catch (e: any) {
      setError(e?.message || "Failed to generate assumptions from filings.");
    } finally {
      setLoading(false);
    }
  };

  const handleRunPmrAgents = async () => {
    const code = normalisedCode.trim();
    if (!code) {
      setError("Enter a product code before running PMR agents.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/product-model-review/${encodeURIComponent(code)}/ai-summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setPmrSummary(data.aiSummary || null);
      setPmrDecision(data.aiDecision || null);
    } catch (e: any) {
      setError(e?.message || "Failed to run PMR AI agents.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="run-detail-page">
      <header className="card">
        <h1>AI Product Review Agent</h1>
        <p className="muted">
          Single-page console that drives the multi-stage AI pipeline: metadata, assumptions, and Product Model Review
          summary / decision suggestion.
        </p>
      </header>

      {error && (
        <section className="card">
          <p className="error">{error}</p>
        </section>
      )}

      <section className="card">
        <h2>1. Product & Filing Hints</h2>
        <p className="muted">
          Start with a rough product code and optional filing id. The AI agents will use these to find relevant filings
          in MinIO and derive metadata and assumptions.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <label htmlFor="agent-product-code">Product code hint</label>
            <input
              id="agent-product-code"
              type="text"
              value={productCode}
              onChange={(e) => setProductCode(e.target.value)}
              placeholder="e.g. ICC18 P18PRUL"
            />
          </div>
          <div className="form-row">
            <label htmlFor="agent-filing-id">Filing ID hint (optional)</label>
            <input
              id="agent-filing-id"
              type="text"
              value={filingId}
              onChange={(e) => setFilingId(e.target.value)}
              placeholder="e.g. PALD-131619832"
            />
          </div>
        </div>
      </section>

      <section className="card">
        <h2>2. Metadata (Stage 1)</h2>
        <p className="muted">
          Let the AI agent infer carrier name, product name, product code, product type, and primary filing id directly
          from the filings.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <button type="button" onClick={handleAutofillMetadata} disabled={loading}>
              {loading ? "Working…" : "Autofill metadata from filings"}
            </button>
          </div>
          <div className="form-row">
            <label>Carrier name</label>
            <input type="text" value={carrierName} onChange={(e) => setCarrierName(e.target.value)} />
          </div>
          <div className="form-row">
            <label>Product name</label>
            <input type="text" value={productName} onChange={(e) => setProductName(e.target.value)} />
          </div>
          <div className="form-row">
            <label>Product type</label>
            <input type="text" value={productType} onChange={(e) => setProductType(e.target.value)} />
          </div>
        </div>
      </section>

      <section className="card">
        <h2>3. Assumptions & DSL (Stage 2)</h2>
        <p className="muted">
          Generate a draft AssumptionSet for this product from its filings. The result is stored in the assumptions
          registry and rendered below for review.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <button type="button" onClick={handleGenerateAssumptions} disabled={loading}>
              {loading ? "Working…" : "Generate AssumptionSet from filings"}
            </button>
          </div>
        </div>
        {assumptionSetJson && (
          <pre className="code-block" style={{ maxHeight: "20rem", overflow: "auto" }}>
            {assumptionSetJson}
          </pre>
        )}
      </section>

      <section className="card">
        <h2>4. PMR Summary & Decision (Stages 4–5)</h2>
        <p className="muted">
          Run the Product Model Review AI agents on the current PMR snapshot for this product. This uses the standard
          PMR builder, then applies an AI summary stage and a draft decision stage.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <button type="button" onClick={handleRunPmrAgents} disabled={loading}>
              {loading ? "Working…" : "Run PMR AI summary & suggestion"}
            </button>
          </div>
        </div>
        {pmrSummary && (
          <div className="pmr-ai-summary">
            <h3>AI Summary</h3>
            <p>{pmrSummary.summary}</p>
            {pmrSummary.key_risks && pmrSummary.key_risks.length > 0 && (
              <>
                <h4>Key risks</h4>
                <ul>
                  {pmrSummary.key_risks.map((r: string, idx: number) => (
                    <li key={idx}>{r}</li>
                  ))}
                </ul>
              </>
            )}
            {pmrSummary.key_gaps && pmrSummary.key_gaps.length > 0 && (
              <>
                <h4>Key gaps</h4>
                <ul>
                  {pmrSummary.key_gaps.map((g: string, idx: number) => (
                    <li key={idx}>{g}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
        {pmrDecision && (
          <div className="pmr-ai-decision">
            <h3>AI Decision Suggestion</h3>
            <p>
              <strong>Suggested decision:</strong> {pmrDecision.suggested_decision || "(none)"}
            </p>
            {pmrDecision.suggested_exclusions && (
              <p>
                <strong>Suggested exclusions:</strong> {pmrDecision.suggested_exclusions}
              </p>
            )}
            {pmrDecision.rationale && pmrDecision.rationale.length > 0 && (
              <>
                <h4>Rationale</h4>
                <ul>
                  {pmrDecision.rationale.map((r: string, idx: number) => (
                    <li key={idx}>{r}</li>
                  ))}
                </ul>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
};
