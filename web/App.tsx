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
      if (view === "create-review" || view === "home") {
        setRunDetail(null);
        setProductReview(null);
        setError(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      try {
        setError(null);

        // POC: when view=product-model, load the static P12TRF product model
        // review JSON. Otherwise, fall back to the existing RunDetail flow.
        if (view === "product-model") {
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
      return <HomePage />;
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


const HomePage: React.FC = () => {
  return (
    <div className="home-page">
      <h1>ActuaryPOC – Home</h1>
      <p className="muted">
        Welcome to the ActuaryPOC dashboard. Start with a new Product Review, inspect the Trust Surface, or drill into
        individual illustration runs.
      </p>

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
