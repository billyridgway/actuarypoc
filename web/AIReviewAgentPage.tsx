import React, { useEffect, useState } from "react";

export const AIReviewAgentPage: React.FC = () => {
  const [productCode, setProductCode] = useState<string>("");
  const [filingId, setFilingId] = useState<string>("");

  const [carrierName, setCarrierName] = useState<string>("");
  const [productName, setProductName] = useState<string>("");
  const [productType, setProductType] = useState<string>("");
  const [metadataApproved, setMetadataApproved] = useState<boolean>(false);
  const [metadataFeedback, setMetadataFeedback] = useState<string>("");

  const [assumptionSetJson, setAssumptionSetJson] = useState<string | null>(null);
  const [assumptionDslPreview, setAssumptionDslPreview] = useState<any | null>(null);
  const [assumptionsApproved, setAssumptionsApproved] = useState<boolean>(false);
  const [assumptionsFeedback, setAssumptionsFeedback] = useState<string>("");
  const [scenarios, setScenarios] = useState<any[] | null>(null);
  const [scenariosApproved, setScenariosApproved] = useState<boolean>(false);
  const [scenariosFeedback, setScenariosFeedback] = useState<string>("");
  const [pmrSummary, setPmrSummary] = useState<any | null>(null);
  const [pmrDecision, setPmrDecision] = useState<any | null>(null);
  const [pmrApproved, setPmrApproved] = useState<boolean>(false);
  const [pmrFeedback, setPmrFeedback] = useState<string>("");
  const [illustrationResult, setIllustrationResult] = useState<any | null>(null);
  const [selectedScenarioIndex, setSelectedScenarioIndex] = useState<number>(0);

  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const [products, setProducts] = useState<any[] | null>(null);
  const [uploadedDocs, setUploadedDocs] = useState<any[] | null>(null);
  const [initialProductCode, setInitialProductCode] = useState<string>("");
  const [mechanics, setMechanics] = useState<any[] | null>(null);
  const [candidateMechanics, setCandidateMechanics] = useState<any[] | null>(null);
  const [mechanicExclusions, setMechanicExclusions] = useState<Record<string, boolean>>({});

  const normalisedCode = (productCode || "").trim();
  const normalisedFiling = (filingId || "").trim();

  useEffect(() => {
    const loadProducts = async () => {
      try {
        const res = await fetch("/api/products");
        if (!res.ok) {
          setProducts([]);
          return;
        }
        const data = await res.json();
        const list = Array.isArray(data?.products) ? data.products : [];
        setProducts(list);
      } catch {
        setProducts([]);
      }
    };

    void loadProducts();
  }, []);

  useEffect(() => {
    const loadMechanics = async () => {
      const code = (productCode || "").trim().toUpperCase();
      if (!code) {
        setMechanics(null);
        setCandidateMechanics(null);
        setMechanicExclusions({});
        return;
      }
      try {
        const res = await fetch(`/api/product-mechanics/${encodeURIComponent(code)}`);
        if (!res.ok) {
          setMechanics(null);
          return;
        }
        const data = await res.json();
        const list = Array.isArray(data?.mechanics) ? data.mechanics : [];
        setMechanics(list.length > 0 ? list : null);
      } catch {
        setMechanics(null);
      }
    };

    void loadMechanics();
  }, [productCode]);

  const handleGenerateMechanics = async () => {
    // Temporary debug logging to verify the handler is wired and see guard state.
    // eslint-disable-next-line no-console
    console.log("[AIReviewAgent] handleGenerateMechanics", {
      productCode,
      normalisedCode,
      metadataApproved,
      loading,
    });

    if (!normalisedCode) {
      setError("Enter a product code before generating mechanics.");
      return;
    }
    if (!metadataApproved) {
      setError("Approve metadata before generating mechanics.");
      return;
    }

    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/product-mechanics/ai-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productCode: normalisedCode,
          filingId: normalisedFiling || undefined,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      // eslint-disable-next-line no-console
      console.log("[AIReviewAgent] mechanics response", data);
      const list = Array.isArray(data?.mechanics) ? data.mechanics : [];
      if (!Array.isArray(data?.mechanics)) {
        setCandidateMechanics(null);
        setMechanicExclusions({});
        setError("Mechanics endpoint returned an unexpected payload shape.");
        return;
      }
      if (list.length === 0) {
        setCandidateMechanics([]);
        setMechanicExclusions({});
        setError("Mechanics extractor ran but did not find any candidate mechanics in the filings.");
        return;
      }

      setCandidateMechanics(list);
      setMechanicExclusions({});
    } catch (e: any) {
      setError(e?.message || "Failed to generate mechanics from filings.");
    } finally {
      setLoading(false);
    }
  };

  const handleApproveMechanics = async () => {
    if (!normalisedCode) {
      setError("Enter a product code before approving mechanics.");
      return;
    }
    if (!candidateMechanics || candidateMechanics.length === 0) {
      setError("Generate mechanics once before approving.");
      return;
    }

    const filtered = candidateMechanics.filter((m, idx) => {
      const key = String(m.id || `${idx}-${m.name || ""}`);
      return !mechanicExclusions[key];
    });
    if (filtered.length === 0) {
      setError("At least one mechanic must be included before approval.");
      return;
    }

    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/product-mechanics/approve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productCode: normalisedCode,
          mechanics: filtered,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const approved = Array.isArray(data?.mechanics) ? data.mechanics : [];
      setMechanics(approved.length > 0 ? approved : null);
      setCandidateMechanics(null);
      setMechanicExclusions({});
    } catch (e: any) {
      setError(e?.message || "Failed to approve mechanics set.");
    } finally {
      setLoading(false);
    }
  };

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
      setMetadataApproved(false);
    } catch (e: any) {
      setError(e?.message || "Failed to autofill metadata from filings.");
    } finally {
      setLoading(false);
    }
  };

  const handleFilesSelected = async (files: FileList | File[]) => {
    let code = normalisedCode;
    // If no product code is set yet, generate a temporary one so uploads
    // have a stable anchor. Later stages (metadata) can propose a
    // product_code derived from filings.
    if (!code) {
      code = `TMP-${Date.now().toString(36)}`;
      setProductCode(code);
      if (!initialProductCode) setInitialProductCode(code);
    } else if (!initialProductCode) {
      setInitialProductCode(code);
    }

    const arr = Array.from(files as any);
    if (arr.length === 0) return;

    setError(null);
    setLoading(true);
    try {
      const allDocs: any[] = [];
      for (const file of arr) {
        const form = new FormData();
        form.append("file", file);
        form.append("kind", "filing");
        form.append("description", file.name);

        const res = await fetch(`/api/product-review/${encodeURIComponent(code)}/documents`, {
          method: "POST",
          body: form,
        });
        if (!res.ok) {
          const text = await res.text();
          throw new Error(text || `HTTP ${res.status}`);
        }
        const payload = await res.json();
        if (Array.isArray(payload?.documents)) {
          allDocs.splice(0, allDocs.length, ...payload.documents);
        }
      }
      setUploadedDocs(allDocs.length > 0 ? allDocs : null);
    } catch (e: any) {
      setError(e?.message || "Failed to upload document(s).");
    } finally {
      setLoading(false);
    }
  };

  const handleRetryMetadataWithFeedback = async () => {
    if (!normalisedCode) {
      setError("Enter at least a product code before retrying metadata.");
      return;
    }
    if (!metadataFeedback.trim()) {
      setError("Provide feedback explaining what needs to change.");
      return;
    }

    setError(null);
    setLoading(true);
    try {
      const previous = {
        carrier_name: carrierName || null,
        product_name: productName || null,
        product_code: productCode || null,
        product_type: productType || null,
        primary_filing_id: filingId || null,
      };
      const res = await fetch("/api/product-review/metadata/suggest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productCodeHint: normalisedCode,
          filingIdHint: normalisedFiling || undefined,
          feedback: metadataFeedback,
          previous,
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
      setMetadataApproved(false);
    } catch (e: any) {
      setError(e?.message || "Failed to retry metadata with feedback.");
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateAssumptions = async () => {
    if (!normalisedCode) {
      setError("Enter a product code before generating assumptions.");
      return;
    }
    if (!metadataApproved) {
      setError("Approve metadata first, then generate assumptions.");
      return;
    }
    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/product-assumptions/ai-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productCode: normalisedCode,
          filingId: normalisedFiling || undefined,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setAssumptionSetJson(JSON.stringify(data.assumptionSet, null, 2));
      setAssumptionDslPreview(data.dslPreview ?? null);
      setAssumptionsApproved(false);
    } catch (e: any) {
      setError(e?.message || "Failed to generate assumptions from filings.");
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateScenarios = async () => {
    if (!normalisedCode) {
      setError("Enter a product code before generating scenarios.");
      return;
    }
    if (!assumptionsApproved) {
      setError("Approve assumptions first, then generate scenarios.");
      return;
    }

    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/product-scenarios/ai-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productCode: normalisedCode,
          filingId: normalisedFiling || undefined,
          productType: productType || undefined,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const scenList = Array.isArray(data.scenarios) ? data.scenarios : [];
      setScenarios(scenList);
      setScenariosApproved(false);
      setSelectedScenarioIndex(0);
    } catch (e: any) {
      setError(e?.message || "Failed to generate scenarios from filings.");
    } finally {
      setLoading(false);
    }
  };

  const handleRetryScenariosWithFeedback = async () => {
    if (!normalisedCode) {
      setError("Enter a product code before retrying scenarios.");
      return;
    }
    if (!scenarios || scenarios.length === 0) {
      setError("Generate scenarios once before retrying.");
      return;
    }
    if (!scenariosFeedback.trim()) {
      setError("Provide feedback explaining what needs to change in the scenarios.");
      return;
    }

    setError(null);
    setLoading(true);
    try {
      const res = await fetch("/api/product-scenarios/ai-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productCode: normalisedCode,
          filingId: normalisedFiling || undefined,
          productType: productType || undefined,
          feedback: scenariosFeedback,
          previous: scenarios,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      const scenList = Array.isArray(data.scenarios) ? data.scenarios : [];
      setScenarios(scenList);
      setScenariosApproved(false);
      setSelectedScenarioIndex(0);
    } catch (e: any) {
      setError(e?.message || "Failed to retry scenarios with feedback.");
    } finally {
      setLoading(false);
    }
  };

  const handleRetryAssumptionsWithFeedback = async () => {
    if (!normalisedCode) {
      setError("Enter a product code before retrying assumptions.");
      return;
    }
    if (!assumptionsFeedback.trim()) {
      setError("Provide feedback explaining what needs to change in the assumptions.");
      return;
    }
    if (!assumptionSetJson) {
      setError("Generate an AssumptionSet once before retrying.");
      return;
    }

    setError(null);
    setLoading(true);
    try {
      let previous: any = null;
      try {
        previous = JSON.parse(assumptionSetJson);
      } catch {
        previous = null;
      }
      const res = await fetch("/api/product-assumptions/ai-generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          productCode: normalisedCode,
          filingId: normalisedFiling || undefined,
          feedback: assumptionsFeedback,
          previous,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setAssumptionSetJson(JSON.stringify(data.assumptionSet, null, 2));
      setAssumptionDslPreview(data.dslPreview ?? null);
      setAssumptionsApproved(false);
    } catch (e: any) {
      setError(e?.message || "Failed to retry assumptions with feedback.");
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
    if (!assumptionsApproved) {
      setError("Approve assumptions first, then run PMR agents.");
      return;
    }
    if (!scenariosApproved) {
      setError("Approve scenarios first, then run PMR agents.");
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
      setPmrApproved(false);
    } catch (e: any) {
      setError(e?.message || "Failed to run PMR AI agents.");
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateIllustration = async () => {
    const code = normalisedCode.trim();
    if (!code) {
      setError("Enter a product code before generating an illustration.");
      return;
    }
    if (!assumptionsApproved || !scenariosApproved) {
      setError("Approve assumptions and scenarios before generating an illustration.");
      return;
    }
    if (!scenarios || scenarios.length === 0) {
      setError("Generate and approve at least one scenario first.");
      return;
    }

    const idx = selectedScenarioIndex >= 0 && selectedScenarioIndex < scenarios.length ? selectedScenarioIndex : 0;
    const scen = scenarios[idx] || {};
    const inputs = scen.inputs || scen;

    const payload: any = {
      age: inputs.age ?? null,
      termYears: inputs.termYears ?? inputs.levelPeriod ?? null,
      riskClass: inputs.riskClass || null,
      smokerClass: inputs.smokerClass || null,
      faceAmount: inputs.faceAmount ?? null,
      premiumMode: inputs.premiumMode || null,
    };

    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/illustrations/${encodeURIComponent(code)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setIllustrationResult(data || null);
    } catch (e: any) {
      setError(e?.message || "Failed to generate illustration.");
    } finally {
      setLoading(false);
    }
  };

  const handleRetryPmrWithFeedback = async () => {
    const code = normalisedCode.trim();
    if (!code) {
      setError("Enter a product code before retrying PMR agents.");
      return;
    }
    if (!pmrFeedback.trim()) {
      setError("Provide feedback explaining what needs to change in the PMR summary/decision.");
      return;
    }
    if (!pmrSummary && !pmrDecision) {
      setError("Run the PMR agents once before retrying.");
      return;
    }

    setError(null);
    setLoading(true);
    try {
      const res = await fetch(`/api/product-model-review/${encodeURIComponent(code)}/ai-summary`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          feedback: pmrFeedback,
          previousSummary: pmrSummary || undefined,
          previousDecision: pmrDecision || undefined,
        }),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = await res.json();
      setPmrSummary(data.aiSummary || null);
      setPmrDecision(data.aiDecision || null);
      setPmrApproved(false);
    } catch (e: any) {
      setError(e?.message || "Failed to retry PMR agents with feedback.");
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
        <h2>0. Upload Filings</h2>
        <p className="muted">
          Start by choosing a product (when known) and uploading SERFF-style PDFs or other filings. Documents are stored
          in MinIO and become the source for all downstream AI stages.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <label htmlFor="agent-product-select">Known products</label>
            <select
              id="agent-product-select"
              value={productCode}
              onChange={(e) => setProductCode(e.target.value)}
            >
              <option value="">(Custom / new product)</option>
              {products &&
                products.map((p) => (
                  <option key={p.productCode} value={p.productCode}>
                    {p.productCode} – {p.productName}
                  </option>
                ))}
            </select>
          </div>
        </div>
        <div
          className="upload-dropzone"
          onDrop={(e) => {
            e.preventDefault();
            if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
              void handleFilesSelected(e.dataTransfer.files);
              e.dataTransfer.clearData();
            }
          }}
          onDragOver={(e) => e.preventDefault()}
          onClick={() => {
            const input = document.getElementById("agent-file-input") as HTMLInputElement | null;
            if (input) input.click();
          }}
        >
          <p>{loading ? "Uploading…" : "Drag & drop filings here, or click to browse."}</p>
          <input
            id="agent-file-input"
            type="file"
            multiple
            style={{ display: "none" }}
            onChange={(e) => {
              if (e.target.files) {
                void handleFilesSelected(e.target.files);
                e.target.value = "";
              }
            }}
          />
        </div>
        {uploadedDocs && uploadedDocs.length > 0 && (
          <>
            <h3>Uploaded documents</h3>
            <table className="kv-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Kind</th>
                  <th>Description</th>
                  <th>Object path</th>
                  <th>Created</th>
                </tr>
              </thead>
              <tbody>
                {uploadedDocs.map((d) => (
                  <tr key={d.id}>
                    <td>{d.id}</td>
                    <td>{d.kind || "filing"}</td>
                    <td>{d.description || "(none)"}</td>
                    <td>{d.objectPath}</td>
                    <td>{d.createdAt ? String(d.createdAt) : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </section>

      <section className="card">
        <h2>1. Metadata (Stage 1)</h2>
        <p className="muted">
          Let the AI agent infer carrier name, product name, product code, product type, and primary filing id directly
          from the filings.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <button type="button" onClick={handleAutofillMetadata} disabled={loading}>
              {loading ? "Working…" : "Autofill metadata from filings"}
            </button>
            <button
              type="button"
              onClick={handleRetryMetadataWithFeedback}
              disabled={loading}
              style={{ marginLeft: "0.5rem" }}
            >
              {loading ? "Working…" : "Reject & retry with feedback"}
            </button>
            <button
              type="button"
              onClick={async () => {
                const oldCode = (initialProductCode || "").trim() || (productCode || "").trim();
                const newCode = (productCode || "").trim();
                if (!oldCode || !newCode) {
                  setError("Cannot finalise metadata without a product code.");
                  return;
                }
                setError(null);
                setLoading(true);
                try {
                  const res = await fetch("/api/product-review/finalize-product-code", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      oldProductCode: oldCode,
                      newProductCode: newCode,
                    }),
                  });
                  if (!res.ok) {
                    const text = await res.text();
                    throw new Error(text || `HTTP ${res.status}`);
                  }
                  setInitialProductCode(newCode);
                  setMetadataApproved(true);
                } catch (e: any) {
                  setError(e?.message || "Failed to finalise metadata and migrate documents.");
                } finally {
                  setLoading(false);
                }
              }}
              disabled={loading}
              style={{ marginLeft: "0.5rem" }}
            >
              Mark metadata as approved (finalise code & docs)
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
          <div className="form-row">
            <label htmlFor="metadata-feedback">Feedback (for retries)</label>
            <textarea
              id="metadata-feedback"
              value={metadataFeedback}
              onChange={(e) => setMetadataFeedback(e.target.value)}
              placeholder="Explain what is wrong or what should change in the metadata."
              rows={3}
            />
          </div>
        </div>
      </section>

      <section className="card">
        <h2>2. Mechanics Discovery &amp; Review</h2>
        <p className="muted">
          Derive an initial Product Mechanics set directly from filings. The AI extractor proposes
          candidate mechanics; you can review them, optionally exclude low-value entries, and then
          approve a mechanics registry for this product. PMR and the Mechanics views will read from
          the approved registry.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <button type="button" onClick={handleGenerateMechanics} disabled={loading}>
              {loading ? "Working…" : "Generate mechanics from filings"}
            </button>
            <button
              type="button"
              onClick={handleApproveMechanics}
              disabled={loading || !candidateMechanics || candidateMechanics.length === 0}
              style={{ marginLeft: "0.5rem" }}
           >
              {loading ? "Working…" : "Approve mechanics set for product"}
            </button>
          </div>
        </div>

        {candidateMechanics && candidateMechanics.length > 0 && (
          <>
            <h3>Candidate mechanics (AI-extracted)</h3>
            <p className="muted">
              Each mechanic below comes from the filings and is marked as <code>source = ai_extracted</code>,
              <code>status = candidate</code>. Uncheck any mechanics you want to exclude before approving
              the set.
            </p>
            <table className="kv-table">
              <thead>
                <tr>
                  <th>Include</th>
                  <th>Mechanic</th>
                  <th>Type</th>
                  <th>Confidence</th>
                  <th>Filing evidence</th>
                </tr>
              </thead>
              <tbody>
                {candidateMechanics.map((m, idx) => {
                  const key = String(m.id || `${idx}-${m.name || ""}`);
                  const excluded = !!mechanicExclusions[key];
                  return (
                    <tr key={key}>
                      <td>
                        <input
                          type="checkbox"
                          checked={!excluded}
                          onChange={(e) => {
                            const checked = e.target.checked;
                            setMechanicExclusions((prev) => {
                              const next = { ...prev };
                              if (!checked) {
                                next[key] = true;
                              } else {
                                delete next[key];
                              }
                              return next;
                            });
                          }}
                        />
                      </td>
                      <td>
                        <strong>{m.name}</strong>
                        <br />
                        <span className="muted" style={{ fontSize: "0.85rem" }}>
                          {m.description}
                        </span>
                      </td>
                      <td>{m.type}</td>
                      <td>{typeof m.confidence === "number" ? `${(m.confidence * 100).toFixed(0)}%` : ""}</td>
                      <td>
                        {m.filing_sources && m.filing_sources.length > 0 ? (
                          <ul>
                            {m.filing_sources.map((fs: any) => (
                              <li key={fs.id}>
                                <span>{fs.document_hint}</span>
                                {fs.page && <span> ({fs.page})</span>}
                                {fs.snippet && <span className="muted"> – {fs.snippet}</span>}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <span className="muted">No filing evidence recorded.</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}

        <h3>Approved mechanics (current registry)</h3>
        {mechanics && mechanics.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Mechanic</th>
                <th>Type</th>
                <th>Confidence</th>
                <th>Filing evidence</th>
                <th>DSL elements</th>
              </tr>
            </thead>
            <tbody>
              {mechanics.map((m) => (
                <tr key={m.id}>
                  <td>
                    <strong>{m.name}</strong>
                    <br />
                    <span className="muted" style={{ fontSize: "0.85rem" }}>
                      {m.description}
                    </span>
                  </td>
                  <td>{m.type}</td>
                  <td>{typeof m.confidence === "number" ? `${(m.confidence * 100).toFixed(0)}%` : ""}</td>
                  <td>
                    {m.filing_sources && m.filing_sources.length > 0 ? (
                      <ul>
                        {m.filing_sources.map((fs: any) => (
                          <li key={fs.id}>
                            <span>{fs.document_hint}</span>
                            {fs.page && <span> ({fs.page})</span>}
                            {fs.snippet && <span className="muted"> – {fs.snippet}</span>}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="muted">No filing evidence recorded.</span>
                    )}
                  </td>
                  <td>
                    {m.dsl_refs && m.dsl_refs.length > 0 ? (
                      <ul>
                        {m.dsl_refs.map((dr: any) => (
                          <li key={dr.id}>
                            <code>{dr.file}</code>
                            {": "}
                            <code>{dr.path}</code>
                            {dr.description && <span className="muted"> – {dr.description}</span>}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <span className="muted">No DSL links recorded.</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No mechanics have been recorded for this product yet.</p>
        )}
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
            <button
              type="button"
              onClick={handleRetryAssumptionsWithFeedback}
              disabled={loading}
              style={{ marginLeft: "0.5rem" }}
            >
              {loading ? "Working…" : "Reject & retry with feedback"}
            </button>
            <button
              type="button"
              onClick={() => setAssumptionsApproved(true)}
              disabled={loading}
              style={{ marginLeft: "0.5rem" }}
            >
              Mark assumptions as approved
            </button>
          </div>
        </div>

        {assumptionDslPreview && (
          <section style={{ marginTop: "1rem" }}>
            <h3>DSL-backed assumptions</h3>
            <p className="muted">
              Preview derived from <code>{assumptionDslPreview.dslFile}</code>. This is what the engine will
              actually use.
            </p>

            {assumptionDslPreview.meta && assumptionDslPreview.meta.risk_class_mapping && (
              <div style={{ marginBottom: "0.75rem" }}>
                <h4>Risk class mapping</h4>
                <table className="kv-table">
                  <thead>
                    <tr>
                      <th>Filed label</th>
                      <th>Engine label</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(assumptionDslPreview.meta.risk_class_mapping).map(([raw, norm]) => (
                      <tr key={raw}>
                        <td>{raw}</td>
                        <td>{String(norm)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {assumptionDslPreview.meta && assumptionDslPreview.meta.mortality_risk_class_mapping && (
              <div style={{ marginBottom: "0.75rem" }}>
                <h4>Mortality risk class mapping</h4>
                <table className="kv-table">
                  <thead>
                    <tr>
                      <th>Engine risk class</th>
                      <th>Mortality table class</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(assumptionDslPreview.meta.mortality_risk_class_mapping).map(([rc, mt]) => (
                      <tr key={rc}>
                        <td>{rc}</td>
                        <td>{String(mt)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {assumptionDslPreview.meta && Array.isArray(assumptionDslPreview.meta.face_bands) && (
              <div style={{ marginBottom: "0.75rem" }}>
                <h4>Face amount bands</h4>
                <table className="kv-table">
                  <thead>
                    <tr>
                      <th>Band</th>
                      <th>Min</th>
                      <th>Max</th>
                    </tr>
                  </thead>
                  <tbody>
                    {assumptionDslPreview.meta.face_bands.map((b: any, idx: number) => (
                      <tr key={b.band ?? idx}>
                        <td>{b.band ?? idx + 1}</td>
                        <td>{b.min ?? "(none)"}</td>
                        <td>{b.max ?? "(none)"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            {assumptionDslPreview.meta && assumptionDslPreview.meta.policy_fee && (
              <div style={{ marginBottom: "0.75rem" }}>
                <h4>Policy fee assumption</h4>
                <p className="muted">
                  Min {assumptionDslPreview.meta.policy_fee.min ?? "?"}, max {" "}
                  {assumptionDslPreview.meta.policy_fee.max ?? "?"}, default {" "}
                  {assumptionDslPreview.meta.policy_fee.default ?? "?"}.
                </p>
              </div>
            )}

            {assumptionDslPreview.charges && assumptionDslPreview.charges.length > 0 && (
              <div style={{ marginBottom: "0.75rem" }}>
                <h4>Charges (from DSL)</h4>
                <ul>
                  {assumptionDslPreview.charges.map((ch: any, idx: number) => (
                    <li key={ch.name || idx}>
                      <strong>{ch.name || "(unnamed)"}</strong>: {ch.formula || "(no formula)"}
                      {ch.description && <span> – {ch.description}</span>}
                      {ch.optional && <span> (optional)</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {assumptionDslPreview.creditRates && assumptionDslPreview.creditRates.length > 0 && (
              <div style={{ marginBottom: "0.75rem" }}>
                <h4>Credit / discount rates (from DSL)</h4>
                <ul>
                  {assumptionDslPreview.creditRates.map((r: any, idx: number) => (
                    <li key={r.rate_type || idx}>
                      <strong>{r.rate_type || "rate"}</strong>: {r.expression || "(no expression)"}
                    {r.description && <span> – {r.description}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {assumptionDslPreview.mechanicAssumptions &&
              assumptionDslPreview.mechanicAssumptions.length > 0 && (
                <div style={{ marginBottom: "0.75rem" }}>
                  <h4>Mechanics-informed extracted assumptions</h4>
                  <p className="muted">
                    These assumptions are extracted from the filings using the approved Product Mechanics as
                    anchors. They are not executable DSL yet.
                  </p>
                  <table className="kv-table">
                    <thead>
                      <tr>
                        <th>Mechanic</th>
                        <th>Filing evidence</th>
                        <th>Extracted assumptions</th>
                      </tr>
                    </thead>
                    <tbody>
                      {assumptionDslPreview.mechanicAssumptions.map((ma: any) => (
                        <tr key={ma.mechanicId}>
                          <td>
                            <strong>{ma.name}</strong>
                            {ma.type && <span className="muted"> ({ma.type})</span>}
                            {ma.description && (
                              <>
                                <br />
                                <span className="muted" style={{ fontSize: "0.85rem" }}>
                                  {ma.description}
                                </span>
                              </>
                            )}
                          </td>
                          <td>
                            {ma.filingSources && ma.filingSources.length > 0 ? (
                              <ul>
                                {ma.filingSources.map((fs: any, idx: number) => (
                                  <li key={fs.id || `${idx}-${fs.document_hint}`}> 
                                    <span>{fs.document_hint}</span>
                                    {fs.page && <span> (p. {fs.page})</span>}
                                  </li>
                                ))}
                              </ul>
                            ) : (
                              <span className="muted">No filing evidence recorded.</span>
                            )}
                          </td>
                          <td>
                            {ma.assumptions && ma.assumptions.length > 0 ? (
                              <ul>
                                {ma.assumptions.map((a: string, idx: number) => (
                                  <li key={idx}>{a}</li>
                                ))}
                              </ul>
                            ) : (
                              <span className="muted">No assumptions extracted yet.</span>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

            {!assumptionDslPreview.meta &&
              (!assumptionDslPreview.charges || assumptionDslPreview.charges.length === 0) &&
              (!assumptionDslPreview.creditRates || assumptionDslPreview.creditRates.length === 0) &&
              (!assumptionDslPreview.mechanicAssumptions ||
                assumptionDslPreview.mechanicAssumptions.length === 0) && (
                <p className="muted">No DSL-backed assumptions were found for this AssumptionSet.</p>
              )}
          </section>
        )}

        {assumptionSetJson && (
          <pre className="code-block" style={{ maxHeight: "20rem", overflow: "auto" }}>
            {assumptionSetJson}
          </pre>
        )}
        <div className="form-grid">
          <div className="form-row">
            <label htmlFor="assumptions-feedback">Feedback (for retries)</label>
            <textarea
              id="assumptions-feedback"
              value={assumptionsFeedback}
              onChange={(e) => setAssumptionsFeedback(e.target.value)}
              placeholder="Explain what is wrong or missing in the AssumptionSet."
              rows={3}
            />
          </div>
        </div>
      </section>

      <section className="card">
        <h2>4. Scenarios (Stage 3)</h2>
        <p className="muted">
          Generate a small set of representative scenarios for this product. These are used as inputs to the Product
          Model Review and illustration stages.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <button type="button" onClick={handleGenerateScenarios} disabled={loading}>
              {loading ? "Working…" : "Generate scenarios from filings"}
            </button>
            <button
              type="button"
              onClick={handleRetryScenariosWithFeedback}
              disabled={loading}
              style={{ marginLeft: "0.5rem" }}
            >
              {loading ? "Working…" : "Reject & retry with feedback"}
            </button>
            <button
              type="button"
              onClick={() => setScenariosApproved(true)}
              disabled={loading}
              style={{ marginLeft: "0.5rem" }}
            >
              Mark scenarios as approved
            </button>
          </div>
        </div>
        {scenarios && scenarios.length > 0 && (
          <table className="kv-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Age</th>
                <th>Sex</th>
                <th>Smoker</th>
                <th>Risk class</th>
                <th>Face</th>
                <th>Term</th>
                <th>Premium mode</th>
              </tr>
            </thead>
            <tbody>
              {scenarios.map((s, idx) => {
                const inputs = s.inputs || s;
                return (
                  <tr key={s.id || idx}>
                    <td>{s.id || idx}</td>
                    <td>{s.name || ""}</td>
                    <td>{inputs.age ?? ""}</td>
                    <td>{inputs.sex || ""}</td>
                    <td>{inputs.smokerClass || ""}</td>
                    <td>{inputs.riskClass || ""}</td>
                    <td>{inputs.faceAmount ?? ""}</td>
                    <td>{inputs.levelPeriod ?? inputs.termYears ?? ""}</td>
                    <td>{inputs.premiumMode || ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        <div className="form-grid">
          <div className="form-row">
            <label htmlFor="scenarios-feedback">Feedback (for retries)</label>
            <textarea
              id="scenarios-feedback"
              value={scenariosFeedback}
              onChange={(e) => setScenariosFeedback(e.target.value)}
              placeholder="Explain what is wrong or missing in the scenario set."
              rows={3}
            />
          </div>
        </div>
      </section>

      <section className="card">
        <h2>5. PMR Summary & Decision (Stages 4–5)</h2>
        <p className="muted">
          Run the Product Model Review AI agents on the current PMR snapshot for this product. This uses the standard
          PMR builder, then applies an AI summary stage and a draft decision stage.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <button type="button" onClick={handleRunPmrAgents} disabled={loading}>
              {loading ? "Working…" : "Run PMR AI summary & suggestion"}
            </button>
            <button
              type="button"
              onClick={handleRetryPmrWithFeedback}
              disabled={loading}
              style={{ marginLeft: "0.5rem" }}
            >
              {loading ? "Working…" : "Reject & retry with feedback"}
            </button>
            <button
              type="button"
              onClick={() => setPmrApproved(true)}
              disabled={loading}
              style={{ marginLeft: "0.5rem" }}
            >
              Mark PMR AI suggestion as approved
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
        <div className="form-grid">
          <div className="form-row">
            <label htmlFor="pmr-feedback">Feedback (for retries)</label>
            <textarea
              id="pmr-feedback"
              value={pmrFeedback}
              onChange={(e) => setPmrFeedback(e.target.value)}
              placeholder="Explain what is wrong or missing in the PMR AI summary/decision."
              rows={3}
            />
          </div>
        </div>
      </section>

      <section className="card">
        <h2>6. Illustration Projection (Final)</h2>
        <p className="muted">
          Generate an illustration-like projection for one of the approved scenarios, using the current product
          configuration and assumptions.
        </p>
        <div className="form-grid">
          <div className="form-row">
            <label htmlFor="scenario-select">Scenario</label>
            <select
              id="scenario-select"
              value={selectedScenarioIndex}
              onChange={(e) => setSelectedScenarioIndex(Number(e.target.value))}
              disabled={!scenarios || scenarios.length === 0}
            >
              {scenarios &&
                scenarios.map((s, idx) => (
                  <option key={s.id || idx} value={idx}>
                    {s.id || idx} – {s.name || "Scenario"}
                  </option>
                ))}
            </select>
          </div>
          <div className="form-row">
            <button type="button" onClick={handleGenerateIllustration} disabled={loading}>
              {loading ? "Working…" : "Generate illustration for selected scenario"}
            </button>
          </div>
        </div>
        {illustrationResult && (
          <>
            {illustrationResult.projection?.metrics && (
              <table className="kv-table">
                <tbody>
                  <tr>
                    <th>Break-even year</th>
                    <td>{illustrationResult.projection.metrics.breakEvenYear ?? "(none)"}</td>
                  </tr>
                  <tr>
                    <th>IRR (to year 10)</th>
                    <td>
                      {typeof illustrationResult.projection.metrics.irr?.toYear10 === "number"
                        ? `${(illustrationResult.projection.metrics.irr.toYear10 * 100).toFixed(2)}%`
                        : "(n/a)"}
                    </td>
                  </tr>
                  <tr>
                    <th>IRR (to year 20)</th>
                    <td>
                      {typeof illustrationResult.projection.metrics.irr?.toYear20 === "number"
                        ? `${(illustrationResult.projection.metrics.irr.toYear20 * 100).toFixed(2)}%`
                        : "(n/a)"}
                    </td>
                  </tr>
                  <tr>
                    <th>IRR (to final year)</th>
                    <td>
                      {typeof illustrationResult.projection.metrics.irr?.toFinalYear === "number"
                        ? `${(illustrationResult.projection.metrics.irr.toFinalYear * 100).toFixed(2)}%`
                        : "(n/a)"}
                    </td>
                  </tr>
                </tbody>
              </table>
            )}
            <table className="kv-table">
              <thead>
                <tr>
                  <th>Year</th>
                  <th>Attained age</th>
                  <th>Premium</th>
                  <th>Cumulative premium</th>
                  <th>Death benefit</th>
                  <th>Cash value</th>
                  <th>Surrender value</th>
                  <th>Net amount at risk</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {Array.isArray(illustrationResult.projection?.rows) &&
                  illustrationResult.projection.rows.map((r: any, idx: number) => (
                    <tr key={idx}>
                      <td>{r.year}</td>
                      <td>{r.attainedAge ?? ""}</td>
                      <td>{r.premium ?? ""}</td>
                      <td>{r.cumulativePremium ?? ""}</td>
                      <td>{r.deathBenefit ?? ""}</td>
                      <td>{r.cashValue ?? ""}</td>
                      <td>{r.surrenderValue ?? ""}</td>
                      <td>{r.netAmountAtRisk ?? ""}</td>
                      <td>{r.status ?? ""}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </>
        )}
      </section>
    </div>
  );
};
