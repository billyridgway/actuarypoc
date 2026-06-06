import React, { useEffect, useState } from "react";
import { RunDetailPage } from "./RunDetailPage";
import type { RunDetail } from "./run-detail.types";
import { ProductModelReviewPage, type ProductModelReview } from "./ProductModelReviewPage";
import { CreateProductReviewPage } from "./CreateProductReviewPage";
import { ProductDetailPage } from "./ProductDetailPage";

export const App: React.FC = () => {
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  const [productReview, setProductReview] = useState<ProductModelReview | null>(null);
  const [products, setProducts] = useState<any[] | null>(null);

  // Object key comes from the URL query (?key=...), falling back to a
  // placeholder. This keeps the frontend dumb: it just calls the backend
  // endpoint and renders the RunDetail it gets back.
  const searchParams = new URLSearchParams(window.location.search);
  const viewParam = searchParams.get("view");
  const view = viewParam || "home";
  const objectKey = searchParams.get("key") || "projections/projection-1779276320.json";
  const productCodeParam = searchParams.get("productCode") || "P12TRF";

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

        // When view is "product-model" or "home" or "product",
        // load the current Product Model Review snapshot. The product
        // detail page will then call its own product-level endpoint.
        if (view === "product-model" || view === "home" || view === "product") {
          const pmrProductCode = view === "product-model" ? productCodeParam || "P12TRF" : "P12TRF";

          const res = await fetch(`/api/product-model-review/${encodeURIComponent(pmrProductCode)}`);
          if (!res.ok) {
            const text = await res.text();
            if (view === "product-model" && (res.status === 404 || res.status === 501)) {
              const msg = `Product Model Review is not implemented for ${pmrProductCode} yet.`;
              throw new Error(msg);
            }
            throw new Error(text || `HTTP ${res.status}`);
          }
          const data: ProductModelReview = await res.json();
          setProductReview(data);
          // When on the Home view, also load the product catalog so the
          // Products section can show all known products, not just P12TRF.
          if (view === "home") {
            try {
              const prodRes = await fetch("/api/products");
              if (prodRes.ok) {
                const prodData = await prodRes.json();
                setProducts(Array.isArray(prodData?.products) ? prodData.products : []);
              } else {
                setProducts([]);
              }
            } catch {
              setProducts([]);
            }
          } else {
            setProducts(null);
          }
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
  }, [objectKey, view, productCodeParam]);

  if (loading && !runDetail && !productReview && view !== "create-review" && view !== "home") {
    return <div className="loading">Loading…</div>;
  }

  const renderContent = () => {
    if (error) {
      return <div className="error">Error loading data: {error}</div>;
    }

    if (view === "home") {
      return <HomePage productReview={productReview} products={products} />;
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

    if (view === "product") {
      if (!productReview) {
        return <div>No product model review data available.</div>;
      }
      return <ProductDetailPage productCode={productCodeParam} />;
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


const HomePage: React.FC<{ productReview: ProductModelReview | null; products: any[] | null }> = ({
  productReview,
  products,
}) => {
  const anyReview: any = productReview;
  const productBlock = anyReview?.product;
  const lastDecision = anyReview?.lastDecision;
  const reviewMeta = anyReview?.reviewMeta;
  const validation = anyReview?.productDefinitionValidation;
  const reviewFreshness = anyReview?.reviewFreshness;
  const scenarioValidation = anyReview?.scenarioValidation;
  const decisionRisk = lastDecision?.decisionRisk;
  const decisionTimeline = anyReview?.decisionTimeline as any;
  const productCode = productBlock?.code || "P12TRF";
  const productName = productBlock?.name || "P12TRF Term (POC)";

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
                  <th>Decision risk</th>
                  <td>
                    {decisionRisk ? (
                      <>
                        <span
                          className={`tag tag--decision-risk-${String(decisionRisk.status || "unknown").toLowerCase()}`}
                        >
                          {String(decisionRisk.status || "unknown").toUpperCase()}
                        </span>
                        {Array.isArray(decisionRisk.reasons)
                          && decisionRisk.reasons.length > 0
                          && decisionRisk.status
                          && String(decisionRisk.status).toLowerCase() !== "clean" && (
                            <ul className="muted">
                              {decisionRisk.reasons.map((r: string, idx: number) => (
                                <li key={idx}>{r}</li>
                              ))}
                            </ul>
                        )}
                      </>
                    ) : (
                      <span className="muted">(no decision risk summary)</span>
                    )}
                  </td>
                </tr>
                <tr>
                  <th>Decision scenario validation</th>
                  <td>
                    {lastDecision?.scenario_validation_status ? (
                      <>
                        <span
                          className={`tag tag--scenario-validation-${lastDecision.scenario_validation_status}`}
                        >
                          {String(lastDecision.scenario_validation_status).toUpperCase()}
                        </span>
                        <span className="muted">
                          {" "}[pass={lastDecision.scenario_validation_pass_count ?? 0}, warning=
                          {lastDecision.scenario_validation_warning_count ?? 0}, fail=
                          {lastDecision.scenario_validation_fail_count ?? 0}]
                        </span>
                      </>
                    ) : (
                      <span className="muted">(no decision scenario validation snapshot)</span>
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
                <tr>
                  <th>Scenario Validation</th>
                  <td>
                    {scenarioValidation ? (
                      <>
                        <span className={`tag tag--scenario-validation-${scenarioValidation.status}`}>
                          {String(scenarioValidation.status).toUpperCase()}
                        </span>
                        {scenarioValidation.summary && (
                          <span className="muted">
                            {" "}[pass={scenarioValidation.summary.pass ?? 0}, warning={scenarioValidation.summary.warning ?? 0}, fail=
                            {scenarioValidation.summary.fail ?? 0}]
                          </span>
                        )}
                      </>
                    ) : (
                      <span className="muted">(no scenario validation data)</span>
                    )}
                  </td>
                </tr>
                <tr>
                  <th>Decision Timeline</th>
                  <td>
                    {decisionTimeline && decisionTimeline.summary ? (
                      <>
                        <span
                          className={`tag tag--decision-risk-${String(
                            decisionTimeline.summary.latestRiskStatus || "unknown",
                          ).toLowerCase()}`}
                        >
                          {String(decisionTimeline.summary.latestRiskStatus || "unknown").toUpperCase()}
                        </span>
                        <span className="muted">
                          {" "}(decisions={decisionTimeline.summary.decisionCount ?? 0},
                          {" "}clean={decisionTimeline.summary.cleanCount ?? 0},
                          {" "}warning={decisionTimeline.summary.warningCount ?? 0},
                          {" "}incomplete={decisionTimeline.summary.incompleteCount ?? 0},
                          {" "}fail={decisionTimeline.summary.failCount ?? 0})
                        </span>
                        {Array.isArray(decisionTimeline.transitions)
                          && decisionTimeline.transitions.length > 0 && (
                            <div className="muted">
                              {(() => {
                                const t = decisionTimeline.transitions[decisionTimeline.transitions.length - 1];
                                if (!t) return null;
                                return (
                                  <>
                                    Most recent change: {t.change || "(unknown)"}
                                    {t.reason ? ` — ${t.reason}` : ""}
                                  </>
                                );
                              })()}
                            </div>
                        )}
                      </>
                    ) : (
                      <span className="muted">(no decision timeline data)</span>
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
        <h2>Products</h2>
        {Array.isArray(products) && products.length > 0 ? (
          <table className="kv-table">
            <thead>
              <tr>
                <th>Product</th>
                <th>Status</th>
                <th>Filing</th>
                <th>Latest generation</th>
                <th>Latest decision</th>
                <th>Freshness</th>
                <th>Risk</th>
              </tr>
            </thead>
            <tbody>
              {products.map((p: any) => {
                const code = p.productCode || "(unknown)";
                const name = p.productName || code;
                const status = p.status || "unknown";
                const latestDecisionId = p.latestDecisionId;
                const latestDecisionLabel = p.latestDecision;
                const freshness = p.reviewFreshnessStatus;
                const risk = p.latestRiskStatus;
                return (
                  <tr key={code}>
                    <td>
                      <a href={`/web?view=product&productCode=${encodeURIComponent(code)}`}>
                        {name} ({code})
                      </a>
                    </td>
                    <td>
                      <span className="muted">{status}</span>
                    </td>
                    <td>{p.filingId || "(not set)"}</td>
                    <td>{p.latestGeneration || "(not set)"}</td>
                    <td>
                      {latestDecisionId != null ? (
                        <>
                          #{latestDecisionId}
                          {latestDecisionLabel ? ` – ${latestDecisionLabel}` : ""}
                        </>
                      ) : (
                        <span className="muted">(none)</span>
                      )}
                    </td>
                    <td>
                      {freshness ? (
                        <span className={`tag tag--freshness-${freshness}`}>
                          {String(freshness).toUpperCase()}
                        </span>
                      ) : (
                        <span className="muted">(unknown)</span>
                      )}
                    </td>
                    <td>
                      {risk ? (
                        <span
                          className={`tag tag--decision-risk-${String(risk || "unknown").toLowerCase()}`}
                        >
                          {String(risk || "unknown").toUpperCase()}
                        </span>
                      ) : (
                        <span className="muted">(unknown)</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : (
          <p className="muted">No products available yet. Generate a Product Review to populate the catalog.</p>
        )}
      </section>

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
            <a href={`/web?view=product&productCode=${encodeURIComponent(productCode)}`} className="button">
              Open Product Review
            </a>
          </p>
        </section>

        <section className="card home-card">
          <h2>Latest Decision / Evidence Bundle</h2>
          <p className="muted">
            View the latest Product Model Review decision history and download or inspect immutable evidence bundles.
          </p>
          <p>
            <a href={`/web?view=product&productCode=${encodeURIComponent(productCode)}`} className="button">
              View Product Decisions &amp; Bundles
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
