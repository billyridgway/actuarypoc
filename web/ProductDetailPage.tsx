import React, { useEffect, useState } from "react";

interface ProductDetailProps {
  productCode: string;
}

interface ProductVersion {
  generationId?: string | null;
  generatedAt?: string | null;
  filingId?: string | null;
  documentCount?: number | null;
  scenarioCount?: number | null;
  latestDecisionId?: number | string | null;
  latestDecisionCreatedAt?: string | null;
  riskStatus?: string | null;
  freshnessStatus?: string | null;
  bundlePath?: string | null;
}

interface ProductDecisionRow {
  id?: number | string | null;
  createdAt?: string | null;
  decision?: string | null;
  reviewer?: string | null;
  riskStatus?: string | null;
  bundlePath?: string | null;
  comments?: string | null;
}

interface ProductDetailPayload {
  product?: {
    productCode?: string | null;
    productName?: string | null;
    filingId?: string | null;
    status?: string | null;
  } | null;
  latestVersion?: ProductVersion | null;
  versions?: ProductVersion[];
  decisions?: ProductDecisionRow[];
}

export const ProductDetailPage: React.FC<ProductDetailProps> = ({ productCode }) => {
  const [detail, setDetail] = useState<ProductDetailPayload | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchDetail = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/products/${encodeURIComponent(productCode)}`);
        if (!res.ok) {
          const text = await res.text();
          if (res.status === 404) {
            throw new Error("Product review is not implemented yet for this product.");
          }
          throw new Error(text || `HTTP ${res.status}`);
        }
        const data = (await res.json()) as ProductDetailPayload;
        setDetail(data);
      } catch (e: any) {
        setError(e?.message || "Failed to load product detail");
      } finally {
        setLoading(false);
      }
    };

    void fetchDetail();
  }, [productCode]);

  if (loading && !detail) {
    return <div className="loading">Loading product detail…</div>;
  }

  if (error) {
    return <div className="error">Error loading product detail: {error}</div>;
  }

  if (!detail || !detail.product) {
    return <div>No product detail available.</div>;
  }

  const product = detail.product;
  const latestVersion = detail.latestVersion || null;
  const versions = detail.versions || [];
  const decisions = detail.decisions || [];

  const productCodeDisplay = product.productCode || productCode;
  const productStatus = (product as any).status || "implemented";

  return (
    <div className="product-detail-page">
      <header className="card">
        <h1>
          Product Detail – {product.productName || productCodeDisplay}
        </h1>
        <p>
          <strong>Product code:</strong> {productCodeDisplay}
        </p>
        <p>
          <strong>Current filing:</strong> {product.filingId || "(not set)"}
        </p>
        <p className="muted">
          {productStatus === "implemented"
            ? "This view summarises Product Model Review generations, decisions, and evidence bundles for this product."
            : "Product review is not implemented for this product yet."}
        </p>
        <p>
          {productStatus === "implemented" && (
            <>
              <a
                href={`/web?view=product-model&productCode=${encodeURIComponent(productCodeDisplay)}`}
                className="button"
              >
                Open Trust Surface
              </a>{" "}
              <a href="/web?view=create-review" className="button">
                Edit / Create Review
              </a>
              {latestVersion && latestVersion.latestDecisionId != null && latestVersion.bundlePath && (
                <>
                  {" "}
                  <a
                    href={`/api/product-model-review/${encodeURIComponent(productCodeDisplay)}/decisions/${encodeURIComponent(String(
                      latestVersion.latestDecisionId,
                    ))}/bundle`}
                    className="button"
                  >
                    Download latest bundle
                  </a>
                </>
              )}
            </>
          )}
        </p>
      </header>

      <section className="card">
        <h2>Latest Version / Generation</h2>
        {latestVersion ? (
          <table className="kv-table">
            <tbody>
              <tr>
                <th>Generation</th>
                <td>{latestVersion.generationId || "(none)"}</td>
              </tr>
              <tr>
                <th>Generated at</th>
                <td>{latestVersion.generatedAt || "(unknown)"}</td>
              </tr>
              <tr>
                <th>Filing</th>
                <td>{latestVersion.filingId || product.filingId || "(not set)"}</td>
              </tr>
              <tr>
                <th>Documents / Scenarios</th>
                <td>
                  {latestVersion.documentCount ?? 0} documents,
                  {" "}
                  {latestVersion.scenarioCount ?? 0} scenarios
                </td>
              </tr>
              <tr>
                <th>Latest decision</th>
                <td>
                  {latestVersion.latestDecisionId != null ? (
                    <>
                      #{latestVersion.latestDecisionId} at {latestVersion.latestDecisionCreatedAt || "(unknown)"}
                    </>
                  ) : (
                    <span className="muted">No decisions recorded for this generation.</span>
                  )}
                </td>
              </tr>
              <tr>
                <th>Risk / Freshness</th>
                <td>
                  <span
                    className={`tag tag--decision-risk-${String(latestVersion.riskStatus || "unknown").toLowerCase()}`}
                  >
                    {String(latestVersion.riskStatus || "unknown").toUpperCase()}
                  </span>
                  {" "}
                  <span className={`tag tag--freshness-${String(latestVersion.freshnessStatus || "unknown").toLowerCase()}`}>
                    {String(latestVersion.freshnessStatus || "unknown").toUpperCase()}
                  </span>
                </td>
              </tr>
            </tbody>
          </table>
        ) : (
          <p className="muted">No versions are available yet for this product.</p>
        )}
      </section>

      <section className="card">
        <h2>Versions</h2>
        {versions.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Generation</th>
                <th>Generated at</th>
                <th>Filing</th>
                <th>Docs</th>
                <th>Scenarios</th>
                <th>Latest decision</th>
                <th>Risk</th>
                <th>Freshness</th>
                <th>Bundle</th>
              </tr>
            </thead>
            <tbody>
              {versions.map((v, idx) => (
                <tr key={v.generationId || idx}>
                  <td>{v.generationId || "(none)"}</td>
                  <td>{v.generatedAt || "(unknown)"}</td>
                  <td>{v.filingId || product.filingId || "(not set)"}</td>
                  <td>{v.documentCount ?? 0}</td>
                  <td>{v.scenarioCount ?? 0}</td>
                  <td>{v.latestDecisionId != null ? `#${v.latestDecisionId}` : "(none)"}</td>
                  <td>
                    <span
                      className={`tag tag--decision-risk-${String(v.riskStatus || "unknown").toLowerCase()}`}
                    >
                      {String(v.riskStatus || "unknown").toUpperCase()}
                    </span>
                  </td>
                  <td>
                    <span
                      className={`tag tag--freshness-${String(v.freshnessStatus || "unknown").toLowerCase()}`}
                    >
                      {String(v.freshnessStatus || "unknown").toUpperCase()}
                    </span>
                  </td>
                  <td>{v.bundlePath || "(none)"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="muted">No versions are available yet.</p>
        )}
      </section>

      <section className="card">
        <h2>Decisions</h2>
        {decisions.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Created at</th>
                <th>Decision</th>
                <th>Reviewer</th>
                <th>Risk</th>
                <th>Bundle</th>
                <th>Comments</th>
              </tr>
            </thead>
            <tbody>
              {decisions.map((d) => {
                const riskStatus = (d.riskStatus || "unknown").toLowerCase();
                return (
                  <tr key={d.id ?? String(d.createdAt ?? Math.random())}>
                    <td>#{d.id}</td>
                    <td>{d.createdAt || "(unknown)"}</td>
                    <td>{d.decision || "(no label)"}</td>
                    <td>{d.reviewer || "(unknown)"}</td>
                    <td>
                      <span className={`tag tag--decision-risk-${riskStatus}`}>
                        {riskStatus.toUpperCase()}
                      </span>
                    </td>
                    <td>{d.bundlePath || "(none)"}</td>
                    <td className="muted">{d.comments || ""}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="muted">No decisions recorded yet.</p>
        )}
      </section>
    </div>
  );
};
