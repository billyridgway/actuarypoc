// Typeset equation rendering (Oct 27, 2026).
//
// The server walks the SAME structured formula body the evaluator
// runs and ships a JSON math tree (see render_math_tree in
// domain/equations.py): division as a stacked fraction, lookups in
// function form, condition chains as cases behind a brace, the fee
// summation as a Σ over the schedule.  This component lays that tree
// out with hand-rolled HTML/CSS — no external typesetting dependency,
// so the app works fully offline.
//
// The equation stands ALONE as its own block.  Timing is a separate
// labeled line underneath.  The prose rendering — plain-English
// fidelity is a product requirement, not a fallback to delete —
// sits behind a small "In words" toggle, collapsed by default
// (Billy, Oct 28, 2026: now that the equation is provided nicely
// typeset, showing the prose all the time is overkill; someone who
// wants it can click).  When the server could not structure a body
// (math is null), the prose stands alone, exactly as before;
// nothing is ever rendered blank or guessed.
//
// FIELD CONTRACT (aligned Oct 27, 2026 against render_math_tree —
// the previous revision had drifted from the server's vocabulary:
// it read cmp operands from left/right (server ships a/b), unary
// children from `of` (server ships x), treated the binary `sub`
// {a, b} as an items list (rendered empty), and had no cases for
// `text` or `min` at all; a cmp or paren node threw and, with no
// error boundary, white-screened the whole app):
//
//   num     {v}                       str   {v}
//   qty     {v, label}                text  {v}
//   add     {items[]}                 mul   {items[]}
//   sub     {a, b}                    div   {num, den}
//   neg     {x}                       pow   {base, exp}
//   paren   {x}                       min   {items[]}
//   max     {items[]}                 cmp   {op, a, b}  (op already a
//   and     {items[]}                         display symbol)
//   or      {items[]}                 not   {x}
//   cases   {rows: [{value, when}]}  — when is a node: a cmp tree
//           for an if-branch, or a text node ("otherwise", or a
//           bands label like "duration in years 1–5")
//   lookup  {name, args[], where: [{field, value}], default?}
//   rows_sum {tableLabel, expr, notes[]}
//
// The renderer tolerates the legacy spellings (left/right, of,
// cond/condText, items-form sub) where they cost nothing, and — the
// standing rule — a node it cannot understand renders NOTHING, and
// any throw inside the math block degrades EquationDisplay to the
// prose caption.  A bad tree must never take the app down again.

import React from "react";

export interface MathNode {
  t: string;
  [key: string]: any;
}

// The server ships cmp ops already translated to display symbols
// ("=", "≠", "≤", …); the name and raw-operator forms are accepted
// too so an older or hand-built tree still renders.
const CMP_SYMBOLS: Record<string, string> = {
  eq: "=",
  ne: "≠",
  lt: "<",
  le: "≤",
  gt: ">",
  ge: "≥",
  "==": "=",
  "!=": "≠",
  "<=": "≤",
  ">=": "≥",
};

const cmpSymbol = (op: unknown): string =>
  CMP_SYMBOLS[String(op)] ?? String(op ?? "");

const itemsOf = (node: MathNode): MathNode[] =>
  Array.isArray(node.items) ? node.items : [];

const childOf = (node: MathNode): MathNode | undefined =>
  node.x ?? node.of ?? undefined;

const MathNodeView: React.FC<{ node: MathNode }> = ({ node }) => {
  // Never throw on a malformed node: a missing or shapeless child
  // renders nothing, and the prose caption still carries the meaning.
  if (!node || typeof node !== "object" || typeof node.t !== "string") {
    return null;
  }
  switch (node.t) {
    case "num":
      return <span className="m-num">{node.v}</span>;
    case "str":
      return <span className="m-str">“{node.v}”</span>;
    case "text":
      return <span className="m-text">{node.v}</span>;
    case "qty":
    case "const_ref":
    case "field":
      return <span className="m-qty">{node.label ?? node.v}</span>;
    case "lookup":
      return (
        <span className="m-lookup">
          <em>{node.name}</em>({(node.args ?? []).join(", ")})
          {(node.where ?? []).length > 0 && (
            <span className="m-note">
              {" "}
              where {(node.where as Array<{ field: string; value: string }>)
                .map((w) => `${w.field} = ${w.value}`)
                .join("; ")}
            </span>
          )}
          {node.default != null && (
            <span className="m-note">
              {" "}
              (or <MathNodeView node={node.default} /> if none filed)
            </span>
          )}
        </span>
      );
    case "div":
      return (
        <span className="m-frac">
          <span className="m-frac-num">
            <MathNodeView node={node.num} />
          </span>
          <span className="m-frac-den">
            <MathNodeView node={node.den} />
          </span>
        </span>
      );
    case "mul":
      return (
        <span className="m-mul">
          {itemsOf(node).map((item: MathNode, i: number) => (
            <React.Fragment key={i}>
              {i > 0 && <span className="m-op"> × </span>}
              <MathNodeView node={item} />
            </React.Fragment>
          ))}
        </span>
      );
    case "add":
      return (
        <span>
          {itemsOf(node).map((item: MathNode, i: number) => (
            <React.Fragment key={i}>
              {i > 0 && <span className="m-op"> + </span>}
              <MathNodeView node={item} />
            </React.Fragment>
          ))}
        </span>
      );
    case "sub": {
      // Binary on the wire: {a, b}.  An items pair is tolerated.
      const a = node.a ?? itemsOf(node)[0];
      const b = node.b ?? itemsOf(node)[1];
      if (a == null && b == null) return null;
      return (
        <span>
          <MathNodeView node={a} /> <span className="m-op">−</span>{" "}
          <MathNodeView node={b} />
        </span>
      );
    }
    case "neg":
      return (
        <span>
          −<MathNodeView node={childOf(node)} />
        </span>
      );
    case "pow":
      return (
        <span className="m-pow">
          <MathNodeView node={node.base} />
          <sup>
            <MathNodeView node={node.exp} />
          </sup>
        </span>
      );
    case "paren":
      return (
        <span className="m-paren">
          (<MathNodeView node={childOf(node)} />)
        </span>
      );
    case "min":
    case "max":
      return (
        <span>
          {node.t}(
          {itemsOf(node).map((item: MathNode, i: number) => (
            <React.Fragment key={i}>
              {i > 0 && ", "}
              <MathNodeView node={item} />
            </React.Fragment>
          ))}
          )
        </span>
      );
    case "cmp": {
      const a = node.a ?? node.left;
      const b = node.b ?? node.right;
      return (
        <span>
          <MathNodeView node={a} />{" "}
          <span className="m-op">{cmpSymbol(node.op)}</span>{" "}
          <MathNodeView node={b} />
        </span>
      );
    }
    case "and":
    case "or":
      return (
        <span>
          {itemsOf(node).map((item: MathNode, i: number) => (
            <React.Fragment key={i}>
              {i > 0 && <span className="m-op"> {node.t} </span>}
              <MathNodeView node={item} />
            </React.Fragment>
          ))}
        </span>
      );
    case "not":
      return (
        <span>
          not (<MathNodeView node={childOf(node)} />)
        </span>
      );
    case "if":
      // The server lowers `if` to cases before shipping; tolerate a
      // raw if-node by lowering it the same way.
      return (
        <MathNodeView
          node={{
            t: "cases",
            rows: [
              { value: node.then, when: node.cond },
              { value: node.else, when: { t: "text", v: "otherwise" } },
            ],
          }}
        />
      );
    case "cases":
      return (
        <span className="m-cases">
          <span className="m-brace" aria-hidden="true">
            {"{"}
          </span>
          <span className="m-case-rows">
            {(Array.isArray(node.rows) ? node.rows : []).map(
              (
                row: {
                  value: MathNode;
                  when?: MathNode | null;
                  cond?: MathNode | null;
                  condText?: string | null;
                },
                i: number,
              ) => (
                <span key={i} className="m-case">
                  <MathNodeView node={row.value} />
                  <span className="m-case-cond">
                    <CaseCondition row={row} />
                  </span>
                </span>
              ),
            )}
          </span>
        </span>
      );
    case "rows_sum":
      return (
        <span className="m-rowsum">
          <span className="m-sigma">
            Σ<sub>{node.tableLabel} rows</sub>
          </span>{" "}
          <MathNodeView node={node.expr} />
          {(node.notes ?? []).length > 0 && (
            <span className="m-note"> — {(node.notes as string[]).join("; ")}</span>
          )}
        </span>
      );
    default:
      // A shape this renderer does not know renders nothing here;
      // the prose caption below still carries the equation.
      return null;
  }
};

// The condition half of one cases row.  On the wire `when` is a
// node: a text node carries the label verbatim ("otherwise", or a
// bands span like "duration in years 1–5"); any other node is the
// branch condition itself.  The legacy {cond, condText} spelling is
// tolerated.
const CaseCondition: React.FC<{
  row: { when?: MathNode | null; cond?: MathNode | null; condText?: string | null };
}> = ({ row }) => {
  const when = row.when ?? row.cond ?? null;
  if (!when) return <> otherwise</>;
  if (when.t === "text") {
    const v = String(when.v ?? "");
    return v === "otherwise" ? <> otherwise</> : <> when {v}</>;
  }
  return (
    <>
      {" "}
      if <MathNodeView node={when} />
      {row.condText ? <> — {row.condText}</> : null}
    </>
  );
};

// Defense in depth: if anything inside the math block still manages
// to throw (a future vocabulary drift, a malformed stored tree), the
// display degrades to the prose caption — never a white screen.
class MathErrorBoundary extends React.Component<
  { fallback: React.ReactNode; children: React.ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError(): { failed: boolean } {
    return { failed: true };
  }

  componentDidCatch(): void {
    // Deliberately silent: the prose fallback is the user-facing
    // behavior; there is no telemetry sink in this app.
  }

  render(): React.ReactNode {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

// The prose rendering behind its toggle (Oct 28, 2026): collapsed
// by default, expanded on click, state per card.  The prose text
// itself is unchanged — this is default visibility only.
const InWordsToggle: React.FC<{
  rendering: string;
  approvalBy?: string | null;
  defaultOpen?: boolean;
}> = ({ rendering, approvalBy, defaultOpen = false }) => {
  const [open, setOpen] = React.useState(defaultOpen);
  return (
    <div className="equation-words-block">
      <button
        type="button"
        className="equation-words-toggle"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        In words {open ? "▾" : "▸"}
      </button>
      {open ? (
        <p className="muted equation-words">
          In words: {rendering}
          {approvalBy ? <> — approved by {approvalBy}</> : null}
        </p>
      ) : null}
    </div>
  );
};

export const EquationDisplay: React.FC<{
  math?: MathNode | null;
  rendering?: string | null;
  timingNote?: string | null;
  approvalBy?: string | null;
  /** Test hook for the render contract: render the "In words"
   *  prose expanded.  Production callers never pass this — the
   *  toggle starts collapsed. */
  defaultWordsOpen?: boolean;
}> = ({ math, rendering, timingNote, approvalBy, defaultWordsOpen = false }) => {
  const prose = rendering ? (
    <p className="muted">
      {rendering}
      {approvalBy ? <> — approved by {approvalBy}</> : null}
    </p>
  ) : null;
  if (!math) return prose;
  return (
    <MathErrorBoundary fallback={prose}>
      <div className="equation-display">
        <div className="equation-math">
          <MathNodeView node={math} />
        </div>
        {timingNote ? <p className="equation-timing">Timing: {timingNote}</p> : null}
        {rendering ? (
          <InWordsToggle
            rendering={rendering}
            approvalBy={approvalBy}
            defaultOpen={defaultWordsOpen}
          />
        ) : null}
      </div>
    </MathErrorBoundary>
  );
};
