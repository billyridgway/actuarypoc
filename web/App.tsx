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
  const view = searchParams.get("view");
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

  if (loading && !runDetail && !productReview && view !== "create-review") {
    return <div className="loading">Loading…</div>;
  }

  if (error) {
    return <div className="error">Error loading data: {error}</div>;
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
