import React, { useEffect, useState } from "react";

interface ProductSummary {
  code: string;
  name: string;
  type: string;
  carrier: string;
}

interface ReviewStateSummary {
  status: string;
  version?: number;
  filingId?: string | null;
  currentGeneration?: string | null;
  generatedAt?: string | null;
  writtenKeys?: string[];
}

interface DocumentSummary {
  id: number | string;
  kind?: string | null;
  description?: string | null;
  objectPath?: string | null;
  createdAt?: string | null;
}

export interface ScenarioRow {
  id?: string;
  name?: string;
  age?: number | null;
  sex?: string | null;
  smokerClass?: string | null;
  riskClass?: string | null;
  faceAmount?: number | null;
  levelPeriod?: number | null;
  premiumMode?: string | null;
  modalPremium?: number | null;
  purpose?: string | null;
  dimensionsExercised?: string[] | null;
  source?: string | null;
}

interface ProductReviewPayload {
  product: ProductSummary;
  review: ReviewStateSummary;
  documents: DocumentSummary[];
  scenarios: ScenarioRow[];
  lastUploaded?: DocumentSummary;
}

const parseNumber = (value: string): number | null => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  return Number.isNaN(n) ? null : n;
};

export const CreateProductReviewPage: React.FC = () => {
  const [step, setStep] = useState<1 | 2 | 3 | 4>(1);

  const [productCode, setProductCode] = useState<string>("P12TRF");
  const [carrierName, setCarrierName] = useState<string>("");
  const [productName, setProductName] = useState<string>("");
  const [productType, setProductType] = useState<string>("Term Life");
  const [filingId, setFilingId] = useState<string>("");

  const [reviewStatus, setReviewStatus] = useState<string>("draft");
  const [currentGeneration, setCurrentGeneration] = useState<string | undefined>(undefined);
  const [generatedAt, setGeneratedAt] = useState<string | undefined>(undefined);
  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [scenarios, setScenarios] = useState<ScenarioRow[]>([]);

  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [savingDraft, setSavingDraft] = useState<boolean>(false);
  const [savingScenarios, setSavingScenarios] = useState<boolean>(false);
  const [uploading, setUploading] = useState<boolean>(false);
  const [generateBusy, setGenerateBusy] = useState<boolean>(false);

  const initialCode = "P12TRF";

  const loadProductReview = async (code: string) => {
    const normalized = (code || "").trim().toUpperCase();
    if (!normalized) return;

    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`/api/product-review/${encodeURIComponent(normalized)}`);
      if (!res.ok) {
        throw new Error(`HTTP ${res.status}`);
      }
      const payload = (await res.json()) as ProductReviewPayload;
      setProductCode(payload.product.code || normalized);
      setCarrierName(payload.product.carrier || "");
      setProductName(payload.product.name || "");
      setProductType(payload.product.type || "Term Life");
      setFilingId(payload.review?.filingId || "");
      setReviewStatus(payload.review?.status || "draft");
      setCurrentGeneration(payload.review?.currentGeneration || undefined);
      setGeneratedAt(payload.review?.generatedAt || undefined);
      setDocuments(payload.documents || []);
      setScenarios((payload.scenarios || []).length > 0 ? payload.scenarios : []);
    } catch (e: any) {
      setError(e?.message || "Failed to load Product Review draft.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    // Load any existing draft / default scenarios for P12TRF to keep the
    // demo fast to show.
    loadProductReview(initialCode).catch(() => {
      // Errors are surfaced via state; nothing else to do here.
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleSaveDraft = async () => {
    const code = (productCode || "").trim().toUpperCase();
    if (!code) {
      setError("Product code is required.");
      return;
    }

    setSavingDraft(true);
    setError(null);
    try {
      const payload = {
        carrier_name: carrierName.trim() || "Carrier (demo)",
        product_name: productName.trim() || "P12TRF Term (demo)",
        product_code: code,
        product_type: productType.trim() || "term",
        filing_id: filingId.trim() || undefined,
      };
      const res = await fetch("/api/product-review/draft", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { product: ProductSummary; review: ReviewStateSummary };
      setProductCode(data.product.code || code);
      setCarrierName(data.product.carrier || carrierName);
      setProductName(data.product.name || productName);
      setProductType(data.product.type || productType);
      setFilingId(data.review?.filingId || filingId);
      setReviewStatus(data.review?.status || "draft");
      setCurrentGeneration(data.review?.currentGeneration || undefined);
      setGeneratedAt(data.review?.generatedAt || undefined);
      setStep(2);
    } catch (e: any) {
      setError(e?.message || "Failed to save Product Review draft.");
    } finally {
      setSavingDraft(false);
    }
  };

  const handleFilesSelected = async (files: FileList | File[]) => {
    const code = (productCode || "").trim().toUpperCase();
    if (!code) {
      setError("Please enter and save product metadata first.");
      return;
    }

    const arr = Array.from(files as any);
    if (arr.length === 0) return;

    setUploading(true);
    setError(null);
    try {
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
        const payload = (await res.json()) as ProductReviewPayload;
        setDocuments(payload.documents || []);
        setReviewStatus(payload.review?.status || reviewStatus);
        setCurrentGeneration(payload.review?.currentGeneration || currentGeneration);
        setGeneratedAt(payload.review?.generatedAt || generatedAt);
      }
    } catch (e: any) {
      setError(e?.message || "Failed to upload document(s).");
    } finally {
      setUploading(false);
    }
  };

  const handleDrop: React.DragEventHandler<HTMLDivElement> = (e) => {
    e.preventDefault();
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      void handleFilesSelected(e.dataTransfer.files);
      e.dataTransfer.clearData();
    }
  };

  const handleDragOver: React.DragEventHandler<HTMLDivElement> = (e) => {
    e.preventDefault();
  };

  const updateScenarioField = (index: number, field: keyof ScenarioRow, value: string) => {
    setScenarios((prev) => {
      const next = [...prev];
      const row = { ...(next[index] || {}) };
      if (field === "age" || field === "faceAmount" || field === "levelPeriod" || field === "modalPremium") {
        (row as any)[field] = parseNumber(value);
      } else {
        (row as any)[field] = value;
      }
      next[index] = row;
      return next;
    });
  };

  const addScenarioRow = () => {
    setScenarios((prev) => [...prev, { id: `S${prev.length + 1}`, name: "New scenario" }]);
  };

  const handleSaveScenarios = async () => {
    const code = (productCode || "").trim().toUpperCase();
    if (!code) {
      setError("Please enter and save product metadata first.");
      return;
    }

    setSavingScenarios(true);
    setError(null);
    try {
      const payload = { scenarios };
      const res = await fetch(`/api/product-review/${encodeURIComponent(code)}/scenarios`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as ProductReviewPayload;
      setScenarios(data.scenarios || []);
      setDocuments(data.documents || documents);
      setReviewStatus(data.review?.status || reviewStatus);
      setCurrentGeneration(data.review?.currentGeneration || currentGeneration);
      setGeneratedAt(data.review?.generatedAt || generatedAt);
      setStep(4);
    } catch (e: any) {
      setError(e?.message || "Failed to save scenarios.");
    } finally {
      setSavingScenarios(false);
    }
  };

  const handleGenerate = async () => {
    const code = (productCode || "").trim().toUpperCase();
    if (!code) {
      setError("Product code is required.");
      return;
    }

    setGenerateBusy(true);
    setError(null);
    try {
      const res = await fetch(`/api/product-review/${encodeURIComponent(code)}/generate`, {
        method: "POST",
      });
      if (!res.ok) {
        const text = await res.text();
        throw new Error(text || `HTTP ${res.status}`);
      }
      const data = (await res.json()) as { redirectUrl?: string };
      const redirectUrl = data.redirectUrl || "/web?view=product-model";
      window.location.href = redirectUrl;
    } catch (e: any) {
      setError(e?.message || "Failed to generate Product Review.");
    } finally {
      setGenerateBusy(false);
    }
  };

  return (
    <div className="run-detail-page">
      <header className="card">
        <h1>Create Product Review – Onboarding (MVP)</h1>
        <p className="muted">
          Lightweight flow to get from filings and scenarios into the Product Model Review Trust Surface. This is a
          demo-focused slice, not a full workflow engine.
        </p>
        <p>
          <strong>Current step:</strong> {step} / 4 &nbsp;·&nbsp; <strong>Review status:</strong> {reviewStatus}
          {filingId && (
            <>
              {" "}
              &nbsp;·&nbsp; <strong>Filing:</strong> {filingId}
            </>
          )}
          {currentGeneration && (
            <>
              {" "}
              &nbsp;·&nbsp; <strong>Generation:</strong> {currentGeneration}
            </>
          )}
        </p>
      </header>

      {error && (
        <section className="card">
          <p className="error">{error}</p>
        </section>
      )}

      {/* 1. Product Setup */}
      <section className="card">
        <h2>1. Product Setup</h2>
        <p className="muted">Capture just enough product metadata to anchor this Product Review.</p>
        <div className="form-grid">
          <div className="form-row">
            <label htmlFor="pr-carrier">Carrier name</label>
            <input
              id="pr-carrier"
              type="text"
              value={carrierName}
              onChange={(e) => setCarrierName(e.target.value)}
              placeholder="e.g. Pacific Life (demo)"
            />
          </div>
          <div className="form-row">
            <label htmlFor="pr-product-name">Product name</label>
            <input
              id="pr-product-name"
              type="text"
              value={productName}
              onChange={(e) => setProductName(e.target.value)}
              placeholder="e.g. ICC12 P12TRF Term (demo)"
            />
          </div>
          <div className="form-row">
            <label htmlFor="pr-product-code">Product code</label>
            <input
              id="pr-product-code"
              type="text"
              value={productCode}
              onChange={(e) => setProductCode(e.target.value)}
            />
          </div>
          <div className="form-row">
            <label htmlFor="pr-product-type">Product type</label>
            <input
              id="pr-product-type"
              type="text"
              value={productType}
              onChange={(e) => setProductType(e.target.value)}
              placeholder="e.g. Level term"
            />
          </div>
          <div className="form-row">
            <label htmlFor="pr-filing-id">Filing ID (optional)</label>
            <input
              id="pr-filing-id"
              type="text"
              value={filingId}
              onChange={(e) => setFilingId(e.target.value)}
              placeholder="e.g. P12TRF-ICC12-2026-DEMO"
            />
          </div>
          <div className="form-row">
            <button type="button" onClick={handleSaveDraft} disabled={savingDraft}>
              {savingDraft ? "Saving draft…" : "Save draft & continue to documents"}
            </button>
          </div>
        </div>
      </section>

      {/* 2. Document Upload */}
      <section className="card">
        <h2>2. Document Upload</h2>
        <p className="muted">
          Drag-and-drop SERFF-style PDFs, Word/Excel memos, or CSVs. Files are stored in MinIO and lightly indexed in
          Postgres, not a full document management system.
        </p>
        <div
          className="upload-dropzone"
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onClick={() => {
            const input = document.getElementById("pr-file-input") as HTMLInputElement | null;
            if (input) input.click();
          }}
        >
          <p>
            {uploading ? "Uploading…" : "Drag & drop PDF, DOCX, XLSX, or CSV here, or click to browse."}
          </p>
          <input
            id="pr-file-input"
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
        <h3>Uploaded documents</h3>
        {documents.length === 0 ? (
          <p className="muted">No documents uploaded yet.</p>
        ) : (
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
              {documents.map((d) => (
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
        )}
      </section>

      {/* 3. Scenario Configuration */}
      <section className="card">
        <h2>3. Scenario Configuration</h2>
        <p className="muted">
          Configure a small set of P12TRF scenarios via form inputs. These are turned into policy test-cases for the
          Trust Surface, not a full pricing grid.
        </p>
        {loading && scenarios.length === 0 ? (
          <p className="muted">Loading default scenarios…</p>
        ) : (
          <>
            <table className="kv-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Label</th>
                  <th>Age</th>
                  <th>Sex</th>
                  <th>Smoker class</th>
                  <th>Risk class</th>
                  <th>Face amount</th>
                  <th>Level period</th>
                  <th>Premium mode</th>
                  <th>Modal premium</th>
                </tr>
              </thead>
              <tbody>
                {scenarios.map((s, idx) => (
                  <tr key={s.id || idx}>
                    <td>
                      <input
                        type="text"
                        value={s.id || ""}
                        onChange={(e) => updateScenarioField(idx, "id", e.target.value)}
                        style={{ width: "4rem" }}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={s.name || ""}
                        onChange={(e) => updateScenarioField(idx, "name", e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        value={s.age ?? ""}
                        onChange={(e) => updateScenarioField(idx, "age", e.target.value)}
                        style={{ width: "4rem" }}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={s.sex || ""}
                        onChange={(e) => updateScenarioField(idx, "sex", e.target.value)}
                        style={{ width: "4rem" }}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={s.smokerClass || ""}
                        onChange={(e) => updateScenarioField(idx, "smokerClass", e.target.value)}
                        style={{ width: "6rem" }}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={s.riskClass || ""}
                        onChange={(e) => updateScenarioField(idx, "riskClass", e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        value={s.faceAmount ?? ""}
                        onChange={(e) => updateScenarioField(idx, "faceAmount", e.target.value)}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        value={s.levelPeriod ?? ""}
                        onChange={(e) => updateScenarioField(idx, "levelPeriod", e.target.value)}
                        style={{ width: "4rem" }}
                      />
                    </td>
                    <td>
                      <input
                        type="text"
                        value={s.premiumMode || ""}
                        onChange={(e) => updateScenarioField(idx, "premiumMode", e.target.value)}
                        style={{ width: "6rem" }}
                      />
                    </td>
                    <td>
                      <input
                        type="number"
                        value={s.modalPremium ?? ""}
                        onChange={(e) => updateScenarioField(idx, "modalPremium", e.target.value)}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="form-row">
              <button type="button" onClick={addScenarioRow}>
                Add scenario
              </button>
            </div>
            <div className="form-row">
              <button type="button" onClick={handleSaveScenarios} disabled={savingScenarios}>
                {savingScenarios ? "Saving scenarios…" : "Save scenarios & review"}
              </button>
            </div>
          </>
        )}
      </section>

      {/* 4. Generate Review */}
      <section className="card">
        <h2>4. Generate Product Review</h2>
        <p className="muted">
          When you click <strong>Generate Product Review</strong>, the system will project the configured P12TRF
          scenarios, refresh the scenario artefacts in MinIO, and redirect you into the existing Product Model Review
          Trust Surface. You can revisit this page at any time to adjust inputs and regenerate.
        </p>
        <table className="kv-table">
          <tbody>
            <tr>
              <th>Product</th>
              <td>
                {productName || "(unnamed)"} ({productCode || "?"}) – {productType || "type unknown"}
              </td>
            </tr>
            <tr>
              <th>Carrier</th>
              <td>{carrierName || "(not set)"}</td>
            </tr>
            <tr>
              <th>Documents (for filing)</th>
              <td>{documents.length}</td>
            </tr>
            <tr>
              <th>Filing</th>
              <td>{filingId || "(not set)"}</td>
            </tr>
            <tr>
              <th>Scenarios</th>
              <td>{scenarios.length}</td>
            </tr>
            <tr>
              <th>Current generation</th>
              <td>{currentGeneration || "(not generated yet)"}</td>
            </tr>
            <tr>
              <th>Generated at</th>
              <td>{generatedAt || "(n/a)"}</td>
            </tr>
          </tbody>
        </table>
        <div className="form-row">
          <button type="button" onClick={handleGenerate} disabled={generateBusy}>
            {generateBusy ? "Generating…" : "Generate Product Review & open Trust Surface"}
          </button>
        </div>
        <div className="form-row">
          <button
            type="button"
            onClick={() => {
              window.location.href = "/web?view=product-model";
            }}
          >
            Open Product Model Review now
          </button>
        </div>
      </section>
    </div>
  );
};
