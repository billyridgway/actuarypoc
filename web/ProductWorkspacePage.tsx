import React from "react";

export const ProductWorkspacePage: React.FC = () => {
  return (
    <div className="home-page">
      <header className="card">
        <h1>Product Understanding Workspace</h1>
        <p className="muted">
          High-level, mostly read-only view of the current product understanding. Use this as the default workspace;
          switch to Expert / Debug mode when you need full control over each pipeline stage.
        </p>
        <p>
          <a href="/web?view=expert" className="button">
            Open Expert / Debug Mode
          </a>
        </p>
      </header>

      <section className="card home-card">
        <h2>Uploaded documents</h2>
        <p className="muted">
          Filings and support documents currently associated with this product. Future slices will surface a live
          summary here; for now, use Expert / Debug mode to manage uploads.
        </p>
      </section>

      <section className="card home-card">
        <h2>Product summary</h2>
        <p className="muted">
          Carrier, product name/code, type, and filing context. This will reuse Product Review metadata once wired
          to the orchestration endpoint.
        </p>
      </section>

      <section className="card home-card">
        <h2>Mechanics discovered</h2>
        <p className="muted">
          Draft mechanics extracted from filings (death benefit, premium rules, charges, surrender behavior, etc.).
          Initially shown as a summary; detailed mechanics editing remains in Expert / Debug mode.
        </p>
      </section>

      <section className="card home-card">
        <h2>Assumptions extracted</h2>
        <p className="muted">
          Mechanics-informed assumptions and AssumptionSet summary. Future work will project the key rates and tables
          here without requiring a separate assumptions stage click.
        </p>
      </section>

      <section className="card home-card">
        <h2>Missing information / gaps</h2>
        <p className="muted">
          Identified gaps and placeholders (e.g. missing COI tables, surrender schedules, or policy fees) plus
          document upload suggestions. This panel will drive the "upload more docs" loop in later slices.
        </p>
      </section>

      <section className="card home-card">
        <h2>Generated scenarios</h2>
        <p className="muted">
          Key test scenarios generated for the product (ages, faces, premium patterns). Initially, this is a
          placeholder; future slices will reuse the AI-generated scenarios and their status.
        </p>
      </section>

      <section className="card home-card">
        <h2>Draft illustration projection</h2>
        <p className="muted">
          When available, a draft illustration-style projection for the selected product. For Promise UL this will
          reuse the existing UL projection path without changing any math.
        </p>
      </section>

      <section className="card home-card">
        <h2>Mechanics explanation / order of operations</h2>
        <p className="muted">
          High-level mechanics trace (order of operations and key cashflow components) for a representative
          projection year. This will reuse the existing UL mechanics explanation once orchestration is wired.
        </p>
      </section>

      <section className="card home-card">
        <h2>PMR / readiness recommendation</h2>
        <p className="muted">
          A readiness snapshot drawing on Product Model Review and scenario validation, indicating whether this
          product is ready for illustration / projection review. For now, consult the Trust Surface and Expert mode
          for full details.
        </p>
      </section>
    </div>
  );
};

