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
// labeled line underneath, and the prose rendering stays as an
// "In words:" caption — plain-English fidelity is a product
// requirement, not a fallback to delete.  When the server could not
// structure a body (math is null), the prose stands alone, exactly
// as before; nothing is ever rendered blank or guessed.

import React from "react";

export interface MathNode {
  t: string;
  [key: string]: any;
}

const CMP_SYMBOLS: Record<string, string> = {
  eq: "=",
  ne: "≠",
  lt: "<",
  le: "≤",
  gt: ">",
  ge: "≥",
};

const MathNodeView: React.FC<{ node: MathNode }> = ({ node }) => {
  switch (node.t) {
    case "num":
      return <span className="m-num">{node.v}</span>;
    case "str":
      return <span className="m-str">“{node.v}”</span>;
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
          {(node.items ?? []).map((item: MathNode, i: number) => (
            <React.Fragment key={i}>
              {i > 0 && <span className="m-op"> × </span>}
              <MathNodeView node={item} />
            </React.Fragment>
          ))}
        </span>
      );
    case "add":
    case "sub":
      return (
        <span>
          {(node.items ?? []).map((item: MathNode, i: number) => (
            <React.Fragment key={i}>
              {i > 0 && <span className="m-op"> {node.t === "add" ? "+" : "−"} </span>}
              <MathNodeView node={item} />
            </React.Fragment>
          ))}
        </span>
      );
    case "neg":
      return (
        <span>
          −<MathNodeView node={node.of} />
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
          (<MathNodeView node={node.of} />)
        </span>
      );
    case "max":
      return (
        <span>
          max(
          {(node.items ?? []).map((item: MathNode, i: number) => (
            <React.Fragment key={i}>
              {i > 0 && ", "}
              <MathNodeView node={item} />
            </React.Fragment>
          ))}
          )
        </span>
      );
    case "cmp":
      return (
        <span>
          <MathNodeView node={node.left} />{" "}
          <span className="m-op">{CMP_SYMBOLS[node.op] ?? node.op}</span>{" "}
          <MathNodeView node={node.right} />
        </span>
      );
    case "and":
    case "or":
      return (
        <span>
          {(node.items ?? []).map((item: MathNode, i: number) => (
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
          not (<MathNodeView node={node.of} />)
        </span>
      );
    case "if":
      return (
        <MathNodeView
          node={{
            t: "cases",
            rows: [
              { value: node.then, cond: node.cond, condText: node.condText ?? null },
              { value: node.else, cond: null, condText: null },
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
            {(node.rows ?? []).map(
              (row: { value: MathNode; cond?: MathNode | null; condText?: string | null }, i: number) => (
                <span key={i} className="m-case">
                  <MathNodeView node={row.value} />
                  <span className="m-case-cond">
                    {row.cond ? (
                      <>
                        {" "}
                        if <MathNodeView node={row.cond} />
                        {row.condText ? <> — {row.condText}</> : null}
                      </>
                    ) : (
                      <> otherwise</>
                    )}
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
      // The server only ships shapes it knows; anything else renders
      // nothing here and the prose caption below still carries it.
      return null;
  }
};

export const EquationDisplay: React.FC<{
  math?: MathNode | null;
  rendering?: string | null;
  timingNote?: string | null;
  approvalBy?: string | null;
}> = ({ math, rendering, timingNote, approvalBy }) => {
  if (!math) {
    if (!rendering) return null;
    return (
      <p className="muted">
        {rendering}
        {approvalBy ? <> — approved by {approvalBy}</> : null}
      </p>
    );
  }
  return (
    <div className="equation-display">
      <div className="equation-math">
        <MathNodeView node={math} />
      </div>
      {timingNote ? <p className="equation-timing">Timing: {timingNote}</p> : null}
      {rendering ? (
        <p className="muted equation-words">
          In words: {rendering}
          {approvalBy ? <> — approved by {approvalBy}</> : null}
        </p>
      ) : null}
    </div>
  );
};
