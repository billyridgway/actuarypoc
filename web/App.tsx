import React, { useEffect, useState } from "react";
import { RunDetailPage } from "./RunDetailPage";
import type { RunDetail } from "./run-detail.types";
import { ProductModelReviewPage, type ProductModelReview } from "./ProductModelReviewPage";
import { CreateProductReviewPage } from "./CreateProductReviewPage";

export const App: React.FC = () => {
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const [productReview, setProductReview] = useState<ProductModelReview | null>(null);

  // Object key comes from the URL query (?key=...), falling back to a
  // placeholder. This keeps the frontend dumb: it just calls the backend
  // endpoint and renders the RunDetail it gets back.
  const searchParams = new URLSearchParams(window.location.search);
  const viewParam = searchParams.get("view");
  const view = viewParam || "home";
  const objectKey = searchParams.get("key") || "projections/projection-1779276320.json";

  useEffect(() => {
    const fetchData = async () => {
      // The onboarding flow has its own data fetching; keep the shared
      // bootstrap simple and skip backend calls for that view.
      if (view === "create-review") {
        setRunDetail(null);
        setProductReview(null);
        setError(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      try {
        setError(null);

        // When view is "product-model" or "home", load the current
        // Product Model Review snapshot. Otherwise, fall back to the
        // existing RunDetail flow.
        if (view === "product-model" || view === "home") {
          const res = await fetch("/api/product-model-review/p12trf");
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
          }
          const data: ProductModelReview = await res.json();
          setProductReview(data);
          setRunDetail(null);
        } else {
          const res = await fetch(`/api/run-detail?key=${encodeURIComponent(objectKey)}`);
          if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
          }
          const data: RunDetail = await res.json();
          setRunDetail(data);
          setProductReview(null);
        }
      } catch (e: any) {
        setError(e.message || "Failed to load data");
      } finally {
        setLoading(false);
      }
    };

    void fetchData();
  }, [objectKey, view]);

  if (loading && !runDetail && !productReview && view !== "create-review" && view !== "home") {
    return <div className="loading">Loading…</div>;
  }

  const renderContent = () => {
    if (error) {
      return <div className="error">Error loading data: {error}</div>;
    }

    if (view === "home") {
      return <HomePage productReview={productReview} />;
    }

    if (view === "create-review") {
      return <CreateProductReviewPage />;
    }

    if (view === "product-model") {
      if (!productReview) {
        return <div>No product model review data available.</div>;
      }
      return <ProductModelReviewPage review={productReview} />;
    }

    if (!runDetail) {
      return <div>No run detail available.</div>;
    }

    return <RunDetailPage runDetail={runDetail} />;
  };

  return (
    <div className="app-shell">
      <header className="top-nav">
        <div className="top-nav__brand">ActuaryPOC</div>
        <nav className="top-nav__links">
          <a href="/web?view=home">Home</a>
          <a href="/web?view=create-review">Create Review</a>
          <a href="/web?view=product-model">Trust Surface</a>
        </nav>
      </header>
      <main className="app-shell__main">{renderContent()}</main>
    </div>
  );
};


const HomePage: React.FC<{ productReview: ProductModelReview | null }> = ({ productReview }) => {
  const anyReview: any = productReview;
  const lastDecision = anyReview?.lastDecision;
  const reviewMeta = anyReview?.reviewMeta;
  const validation = anyReview?.productDefinitionValidation;
  const reviewFreshness = anyReview?.reviewFreshness;

  const shortenHash = (hash?: string | null, length = 8): string | null => {
    if (!hash) return null;
    return hash.length > length ? hash.slice(0, length) : hash;
  };

  return (
    <div className="home-page">
      <h1>ActuaryPOC – Home</h1>
      <p className="muted">
        Welcome to the ActuaryPOC dashboard. Start with a new Product Review, inspect the Trust Surface, or drill into
        individual illustration runs.
      </p>

      <section className="card home-card">
        <h2>Current Product Model Review Status (P12TRF)</h2>
        {productReview ? (
          <>
            <p className="muted">
              Snapshot from <code>/api/product-model-review/p12trf</code>. For full details, open the Trust Surface.
            </p>
            <table className="kv-table">
              <tbody>
                <tr>
                  <th>Current filing</th>
                  <td>{reviewMeta?.filingId || "(not set)"}</td>
                </tr>
                <tr>
                  <th>Current generation</th>
                  <td>{reviewMeta?.currentGeneration || "(not set)"}</td>
                </tr>
                <tr>
                  <th>Validation status</th>
                  <td>
                    {lastDecision?.validation_status
                      || validation?.status
                      || "(unknown)"}
                    {lastDecision?.validation_pass_count != null && (
                      <span className="muted">
                        {" "}[pass={lastDecision.validation_pass_count}, warning=
                        {lastDecision.validation_warning_count ?? 0}, fail=
                        {lastDecision.validation_fail_count ?? 0}]
                      </span>
                    )}
                  </td>
                </tr>
                <tr>
                  <th>Latest decision</th>
                  <td>
                    {lastDecision?.id != null ? (
                      <>
                        #{lastDecision.id} – {lastDecision.decision || "(no label)"} by {lastDecision.reviewer || "(unknown)"}
                        {lastDecision.created_at && (
                          <span className="muted"> at {lastDecision.created_at}</span>
                        )}
                      </>
                    ) : (
                      <span className="muted">No decisions recorded yet.</span>
                    )}
                  </td>
                </tr>
                <tr>
                  <th>Latest bundle</th>
                  <td>
                    {lastDecision?.bundle_path ? (
                      <>
                        <div>Path: {lastDecision.bundle_path}</div>
                        <div>
                          Hash: {lastDecision.bundle_hash ? shortenHash(lastDecision.bundle_hash, 12) : "(n/a)"}
                          {lastDecision.bundle_hash && (
                            <span className="muted"> ({lastDecision.bundle_hash})</span>
                          )}
                        </div>
                      </>
                    ) : (
                      <span className="muted">No evidence bundle recorded for the latest decision.</span>
                    )}
                  </td>
                </tr>
                <tr>
                  <th>Review Freshness</th>
                  <td>
                    {reviewFreshness ? (
                      <>
                        <span className={`tag tag--freshness-${reviewFreshness.status}`}>
                          {String(reviewFreshness.status).toUpperCase()}
                        </span>
                        {Array.isArray(reviewFreshness.messages) && reviewFreshness.messages.length > 0 && (
                          <ul className="muted">
                            {reviewFreshness.messages.map((m: string, idx: number) => (
                              <li key={idx}>{m}</li>
                            ))}
                          </ul>
                        )}
                      </>
                    ) : (
                      <span className="muted">(no freshness data)</span>
                    )}
                  </td>
                </tr>
              </tbody>
            </table>
            <p>
              <a href="/web?view=product-model" className="button">
                Open Trust Surface
              </a>
            </p>
          </>
        ) : (
          <p className="muted">
            No Product Model Review data is available yet. Generate a review from the Create Product Review flow.
          </p>
        )}
      </section>

      <div className="home-grid">
        <section className="card home-card">
          <h2>Create Product Review</h2>
          <p className="muted">
            Configure product metadata and filing context, upload documents, configure scenarios, and generate a Product
            Model Review.
          </p>
          <p>
            <a href="/web?view=create-review" className="button">
              Go to Create Review
            </a>
          </p>
        </section>

        <section className="card home-card">
          <h2>Product Model Review / Trust Surface</h2>
          <p className="muted">
            Review the ProductDefinition, coverage matrix, validation results, evidence links, and Product Model Review
            decisions and bundles for P12TRF.
          </p>
          <p>
            <a href="/web?view=product-model" className="button">
              Open Trust Surface
            </a>
          </p>
        </section>

        <section className="card home-card">
          <h2>Latest Decision / Evidence Bundle</h2>
          <p className="muted">
            View the latest Product Model Review decision history and download or inspect immutable evidence bundles.
          </p>
          <p>
            <a href="/web?view=product-model" className="button">
              View Decisions &amp; Bundles
            </a>
          </p>
        </section>

        <section className="card home-card">
          <h2>Run Detail / Illustration Viewer</h2>
          <p className="muted">
            Inspect a single projection run with premium comparison, projection graphs, and audit information. Requires
            a projection object key.
          </p>
          <p className="muted">
            The default example uses the fallback key configured in the app; you can also supply <code>?key=…</code> in
            the URL for other runs.
          </p>
          <p>
            <a href="/web" className="button">
              Open Run Detail (example)
            </a>
          </p>
        </section>
      </div>
    </div>
  );
};
