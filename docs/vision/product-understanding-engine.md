# Product Understanding Engine – Long-Lived Vision

> **Status:** Governing strategy document (long-lived). Treat this as a source of truth when making architectural or roadmap decisions.
>
> **Scope:** Actuary AI / Insurance Illustration Platform (ActuaryPOC + Operator + PMR UI).

---

## 1. Core Insight – From Model Review to Product Understanding

The purpose of Actuary AI is evolving from:

- **"Review actuarial models"**

into:

- **"Understand insurance products directly from filings and transform that understanding into executable product definitions."**

The long-term value of this system is not merely verifying models.
The long-term value is **understanding insurance products.**

The target end-to-end flow is:

```text
Filing
→ Product Understanding
→ Product Mechanics
→ Executable Product Definition
→ Projection
→ Validation / Trust Surface
```

Concretely, the system should be able to ingest a filing (forms, actuarial memo, SOV, rate grids, riders) and derive:

1. A **structured understanding** of what the product does and how it behaves.
2. A **Product Mechanics Graph** describing premiums, charges, benefits, and relationships.
3. An **executable product definition** (DSL + tables) that the projection engine can run.
4. A **validation and explanation layer** (Trust Surface) that ties results back to filings and mechanics.

Any future work that meaningfully improves this end-to-end capability is *core* to the product.

---

## 2. Product Mechanics Graph – Canonical Product Representation

### 2.1 Concept

Introduce a first-class concept:

> **Product Mechanics Graph** – the canonical representation of how a product works.

This graph lives *between* filings and the executable DSL. It captures the **semantics** of the product, not just code or table layouts.

Examples of mechanics that should become explicit nodes:

- Premium
- Premium Load
- Account Value
- COI Charge
- Policy Fee
- Interest Crediting
- Surrender Charge
- Riders
- Benefits
- Conversion Features
- Guarantees / Floors / Caps
- Nonforfeiture features

Each **mechanic node** should carry:

- **Semantic meaning** – what concept this mechanic represents in the product (e.g. "monthly cost of insurance charge against account value").
- **Calculation behavior** – how it is computed conceptually (inputs, outputs, timing, aggregation; not necessarily raw code).
- **Filing evidence** – which documents and sections support this mechanic.
- **Source pages** – page/section references.
- **Extracted text** – relevant snippets that justify the mechanic.
- **Confidence** – how confident the system is in this mechanic (and why).
- **Relationships** – edges to other mechanics (e.g. "COI charge reduces account value", "premium load applies to premium", "conversion feature depends on base coverage").

Over time, this graph becomes the **single source of truth** for what a product *is*.

### 2.2 Position in the Architecture

The mechanics graph sits between filings and DSL:

```text
Filing (SERFF / docs / memos)
↓
Product Mechanics Graph
↓
DSL (executable product definition)
↓
Projection Engine
↓
Trust Surface (validation & explanation)
```

The DSL should be derivable from the Product Mechanics Graph.
The Trust Surface should be able to:

- render views of the mechanics graph, and
- navigate from mechanics to DSL to projections and back to filings.

Any new feature that touches filings, DSL, projections, or PMR should respect this layering and move the system toward a **mechanics-first** internal model.

---

## 3. DSL Philosophy – From Human Authorship to AI Interpretation

Historically, the DSL has been treated as something **humans author** to describe products.

Going forward, the DSL should be viewed as:

> **"The AI's executable interpretation of the filing."**

Humans still matter, but their role shifts:

- AI:
  - extracts mechanics from filings,
  - constructs / updates the Product Mechanics Graph,
  - proposes DSL (charges, credit rates, meta, flags, tables wiring) from that graph.
- Humans:
  - review AI-proposed mechanics and DSL,
  - challenge and correct incorrect interpretations,
  - approve product definitions for use in projections / PMR / illustrations.

### 3.1 Target Workflow

Future target loop for a new (or changed) product:

```text
AI extracts mechanics from filings
→ AI builds / updates Product Mechanics Graph
→ AI proposes DSL from the mechanics graph
→ Human reviews mechanics + DSL (with traceability back to filings)
→ Human approves product definition for use
→ Projections + PMR use the approved definition
```

The DSL remains version-controlled and human-readable, but it is **primarily an AI-generated artefact** anchored in filings and mechanics, not a hand-crafted spec disconnected from evidence.

---

## 4. Trust Surface – Positioning in the Stack

The **Product Model Review / Trust Surface** remains strategically important.
It is where actuaries and reviewers:

- see how the engine interprets the product,
- inspect scenarios and evidence,
- make approval decisions.

However, the Trust Surface is **not the product**.

It is a **validation and explanation layer** built *on top of* product understanding and projection.

The strategic hierarchy should be:

```text
Product Understanding Engine (filings → mechanics → DSL)
↓
Projection Engine (executing the DSL)
↓
Trust Surface (validation, explanation, decision)
```

**Not:**

```text
Trust Surface
↓
Everything else
```

Design and roadmap decisions should reflect this:

- We do not build UX-only features that are disconnected from filings and mechanics.
- We prioritize investments that deepen understanding (and thus make the Trust Surface more meaningful) over purely cosmetic or workflow UI improvements.

---

## 5. DSL Traceability – "Why Does This Value Exist?"

Every DSL element should be traceable to:

- A **Product Mechanics Graph node** (what mechanic is this? how is it used?).
- **Filing evidence** (which documents, which sections, which pages).
- **Source document + page reference** (or equivalent locators).
- **Extracted text** (the clause or table that motivated this value or formula).

Future users should be able to ask:

> **"Why does this DSL value exist?"**

and immediately see:

- which mechanic it belongs to,
- which filings back it up,
- what the relevant text says,
- and how confident the system is.

This traceability needs to be **bidirectional**:

- From DSL → mechanics → filings.
- From filing text → mechanics → DSL → projection behavior.

---

## 6. Filing Traceability – Bidirectional Links

The future architecture should support rich, bidirectional traceability across the stack:

```text
Filing Evidence
↔ Product Mechanics
↔ DSL
↔ Projection Results
↔ Trust Surface Findings
```

Examples:

- Starting at a **filing page**:
  - see which mechanics the system inferred from that page,
  - see which DSL elements implement those mechanics,
  - see which projections and scenarios exercise those mechanics,
  - see what the Trust Surface says about them (gaps, warnings, approvals).

- Starting at a **projection anomaly** in the Trust Surface:
  - see which DSL element and mechanic drove it,
  - jump back to the filing evidence and text that justified that mechanic.

Bidirectional traceability is a **core design goal**, not a nice-to-have.
Any schema, storage, or API decision that makes traceability harder should be treated as technical debt.

---

## 7. Prioritization Guidance – Understanding First

When evaluating future work, ask:

> **"Does this improve our ability to understand the insurance product itself?"**

If the answer is **yes**, especially for:

- filing extraction,
- product mechanics extraction,
- mechanics visualization,
- DSL generation from mechanics,
- evidence traceability,
- filing provenance and audit,

then the work is **strategic** and should be **prioritized aggressively.**

If the answer is **no**, or only weakly yes, treat the work as **secondary** unless it is required to keep the system operational.

Examples of **secondary** (but still useful) areas:

- reviewer workflows (queues, multi-step approvals),
- notifications and reminders,
- permissions and roles,
- approval routing / escalations,
- advisor or customer-facing portals,
- administrative tooling around already-understood products.

These features matter, but they should **not become the primary focus** until the product understanding engine is mature and reliable.

---

## 8. Existing Assets to Preserve (and Reposition)

The current system already has valuable components that should be preserved and repositioned beneath the Product Understanding layer:

- **Projection Engine** – executes the DSL against actuarial tables and inputs; remains the core execution layer.
- **Product DSL** – becomes the AI-generated, human-reviewed executable representation of the mechanics graph.
- **Assumption Registry** – continues as a registry of product-specific assumptions; may evolve to reference mechanics and filings more directly.
- **Product Model Review Trust Surface** – the main validation and explanation UI; should be fed by mechanics-aware DSL and projections.
- **Scenario Evidence** – scenario catalog and checks; should evolve to explicitly exercise mechanics and document which mechanics are covered.
- **Onboarding Flow (Product Review onboarding)** – remains useful to seed product context and filings, but should be extended to surface and correct mechanics.
- **Operator Architecture (CRDs + Jobs + MinIO)** – remains the backbone for batch projections and artefact storage; over time, it should become mechanics-aware (e.g. tracking which mechanics/DSL versions were used per run).

None of these should be thrown away.
They should instead be **repositioned under the Product Understanding Engine** and gradually wired to the Product Mechanics Graph and filing traceability.

---

## 9. Strategic Question for New Features

For every major feature proposal or roadmap item, explicitly answer:

> **"How does this help us understand an insurance product from its filing?"**

- If the answer is **strong and concrete** (e.g. "it improves mechanics extraction for riders and conversion features and ties them back to filings"), the feature is likely aligned with this vision.
- If the answer is **weak or indirect** (e.g. "it adds another approval status flag in the UI"), the feature may still be useful but should be reconsidered or deprioritized relative to understanding work.

Future roadmap documents, ADRs, and planning notes should *explicitly* state whether a given item advances the **Product Understanding Engine** vision and how.

---

## 10. Implications for Current Roadmap

When reviewing existing roadmap and backlog items:

- **Accelerate** items that:
  - deepen filing extraction,
  - build a Product Mechanics Graph or equivalent representation,
  - generate DSL (or parts of it) from mechanics,
  - strengthen evidence and filing traceability,
  - visualize mechanics and their relationships.

- **Maintain** items that:
  - improve the projection engine,
  - enhance PMR / Trust Surface *when they expose or explain mechanics and evidence*,
  - improve operator + MinIO wiring to track which product definitions and mechanics were used for each run.

- **De-emphasize** or sequence later items that focus primarily on:
  - workflow UX,
  - reviewer dashboards and routing,
  - external advisor/customer portals,
  - non-critical admin tooling,
  - purely cosmetic UI changes.

As new roadmap documents are created or updated:

1. **Reference this document** explicitly.
2. For each significant item, mark whether it is:
   - **PUE-aligned (Product Understanding Engine)**, or
   - **Supporting / non-PUE**.
3. Prefer delivering a thin but end-to-end **product understanding slice** (filing → mechanics → DSL → projection → Trust Surface) over broad but shallow UI or workflow work.

---

## 11. How to Use This Document

- When adding or updating **architecture docs** or **backlog/roadmap docs**, link to this file and state how the described work fits (or does not fit) the Product Understanding Engine vision.
- When designing new features, explicitly describe their relationship to:
  - filings,
  - mechanics graph,
  - DSL,
  - projections,
  - Trust Surface.
- When making trade-offs, prefer improvements that make the system **better at understanding products from filings** over generic platform polish.

If a future change appears to conflict with this document, the change should either:

- update this vision file with a clear rationale, or
- be reconsidered.
