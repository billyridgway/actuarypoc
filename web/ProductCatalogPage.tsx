import React from "react";

interface CatalogProduct {
  productCode: string;
  productName?: string;
  productType?: string;
  carrier?: string;
  understandingStatus?: string;
  documentCount?: number | null;
  projectionAvailable?: boolean;
  workspaceAvailable?: boolean;
  complianceStatus?: string;
  complianceImplemented?: number | null;
  compliancePartial?: number | null;
  complianceMissing?: number | null;
  reviewEndpoint?: string | null;
}

interface ProductsResponse {
  products?: any[];
}

const normaliseUnderstandingLabel = (value?: string | null): string => {
  const v = (value || "").toLowerCase();
  if (!v) return "Unknown";
  if (v === "green") return "Green";
  if (v === "yellow") return "Yellow";
  if (v === "red") return "Red";
  return value || "Unknown";
};

const normaliseComplianceLabel = (value?: string | null): string => {
  const v = (value || "").toLowerCase();
  if (!v) return "Unknown";
  if (v === "green") return "Green";
  if (v === "yellow") return "Yellow";
  if (v === "red") return "Red";
  return "Unknown";
};

export const ProductCatalogPage: React.FC = () => {
  const [products, setProducts] = React.useState<CatalogProduct[]>([]);
  const [loading, setLoading] = React.useState<boolean>(true);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        setLoading(true);
        setError(null);
        const resp = await fetch("/api/products");
        if (!resp.ok) {
          const text = await resp.text();
          throw new Error(text || `HTTP ${resp.status}`);
        }
        const body: ProductsResponse = await resp.json();
        const raw = body.products || [];
        if (!Array.isArray(raw)) {
          if (!cancelled) setProducts([]);
          return;
        }

        const mapped: CatalogProduct[] = raw.map((p: any) => {
          const compliance = p.complianceSummary || {};
          return {
            productCode: String(p.productCode || "").toUpperCase(),
            productName: p.productName,
            productType: p.productType,
            carrier: p.carrier,
            understandingStatus: p.understandingStatus,
            documentCount: typeof p.documentCount === "number" ? p.documentCount : null,
            projectionAvailable: Boolean(p.projectionAvailable),
            workspaceAvailable: Boolean(p.workspaceAvailable),
            complianceStatus: compliance.overallStatus || null,
            complianceImplemented:
              typeof compliance.implemented === "number" ? compliance.implemented : null,
            compliancePartial:
              typeof compliance.partial === "number" ? compliance.partial : null,
            complianceMissing:
              typeof compliance.missing === "number" ? compliance.missing : null,
            reviewEndpoint: p.reviewEndpoint ?? null,
          };
        });

        if (!cancelled) setProducts(mapped);
      } catch (err: any) {
        if (!cancelled) setError(err?.message || "Failed to load products.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const hasProducts = products.length > 0;

  return (
    <div className="home-page">
      <section className="card home-card">
        <h2>Product Catalog</h2>
        <p className="muted">
          Select a product to open its Product Understanding Workspace, or use Expert / Debug mode for detailed
          pipeline control.
        </p>
        {loading && <p className="muted">Loading products…</p>}
        {error && !loading && <p className="error">{error}</p>}
        {!loading && !error && !hasProducts && (
          <p className="muted">No products are registered yet. Use the Add Product card below to start onboarding.</p>
        )}

        {hasProducts && (
          <div className="catalog-grid">
            {products.map((p) => {
              const name = p.productName || p.productCode;
              const type = p.productType || "(type not set)";
              const understanding = normaliseUnderstandingLabel(p.understandingStatus);
              const docCountLabel =
                typeof p.documentCount === "number" ? String(p.documentCount) : "(unknown)";
              const projectionLabel = p.projectionAvailable ? "Available" : "Not available";
              const complianceLabel = normaliseComplianceLabel(p.complianceStatus);

              const workspaceHref = `/web?product=${encodeURIComponent(p.productCode)}`;
              const canOpenWorkspace = Boolean(p.workspaceAvailable);
              const canOpenExpert = !canOpenWorkspace && !!p.reviewEndpoint;

              let ctaLabel = "Workspace coming soon";
              let ctaHref: string | undefined;
              let ctaDisabled = true;

              if (canOpenWorkspace) {
                ctaLabel = "Open workspace";
                ctaHref = workspaceHref;
                ctaDisabled = false;
              } else if (canOpenExpert) {
                ctaLabel = "Open Expert / Trust Surface";
                ctaHref = p.reviewEndpoint || undefined;
                ctaDisabled = false;
              }

              return (
                <div key={p.productCode} className="card home-card">
                  <h3>{name}</h3>
                  <p className="muted">
                    <strong>Code:</strong> {p.productCode}
                    <br />
                    <strong>Type:</strong> {type}
                  </p>
                  <table className="kv-table">
                    <tbody>
                      <tr>
                        <th>Understanding</th>
                        <td>{understanding}</td>
                      </tr>
                      <tr>
                        <th>Documents</th>
                        <td>{docCountLabel}</td>
                      </tr>
                      <tr>
                        <th>Projection</th>
                        <td>{projectionLabel}</td>
                      </tr>
                      <tr>
                        <th>Compliance</th>
                        <td>
                          {complianceLabel}
                          {p.complianceImplemented != null && (
                            <span className="muted">{` - Impl: ${p.complianceImplemented}, Part: ${
                              p.compliancePartial ?? 0
                            }, Miss: ${p.complianceMissing ?? 0}`}</span>
                          )}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                  <p>
                    {ctaHref ? (
                      <a href={ctaHref} className="button">
                        {ctaLabel}
                      </a>
                    ) : (
                      <button className="button" disabled={ctaDisabled}>
                        {ctaLabel}
                      </button>
                    )}
                  </p>
                </div>
              );
            })}
          </div>
        )}
      </section>

      <section className="card home-card">
        <h2>Add Product</h2>
        <p className="muted">
          This is a placeholder for the future onboarding flow. Upload key filings and enter basic product metadata to
          register a new product in the catalog.
        </p>
        <div className="add-product-form">
          <div className="form-row">
            <label>
              Product code
              <input type="text" placeholder="e.g. P12TRF" disabled />
            </label>
          </div>
          <div className="form-row">
            <label>
              Product name
              <input type="text" placeholder="e.g. Pacific Life ICC12 P12TRF Term" disabled />
            </label>
          </div>
          <div className="form-row">
            <label className="button button-secondary">
              Upload filings (coming soon)
              <input type="file" multiple style={{ display: "none" }} disabled />
            </label>
          </div>
          <p className="muted">Storing new products and filings is not yet wired in this slice.</p>
        </div>
      </section>
    </div>
  );
};
