import React, { useEffect, useState } from "react";
import { RunDetailPage } from "./RunDetailPage";
import type { RunDetail } from "./run-detail.types";

export const App: React.FC = () => {
  const [runDetail, setRunDetail] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);

  // Object key comes from the URL query (?key=...), falling back to a
  // placeholder. This keeps the frontend dumb: it just calls the backend
  // endpoint and renders the RunDetail it gets back.
  const searchParams = new URLSearchParams(window.location.search);
  const objectKey = searchParams.get("key") || "projections/projection-1779276320.json";

  useEffect(() => {
    const fetchRunDetail = async () => {
      setLoading(true);
      try {
        setError(null);
        const res = await fetch(`/api/run-detail?key=${encodeURIComponent(objectKey)}`);
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        const data: RunDetail = await res.json();
        setRunDetail(data);
      } catch (e: any) {
        setError(e.message || "Failed to load run detail");
      } finally {
        setLoading(false);
      }
    };

    fetchRunDetail();
  }, [objectKey]);

  if (loading && !runDetail) {
    return <div className="loading">Loading…</div>;
  }

  if (error) {
    return <div className="error">Error loading run detail: {error}</div>;
  }

  if (!runDetail) {
    return <div>No run detail available.</div>;
  }

  return <RunDetailPage runDetail={runDetail} />;
};
