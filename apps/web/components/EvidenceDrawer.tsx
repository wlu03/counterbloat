"use client";

import { useState } from "react";
import { api, type Calculation, type Evidence } from "@/lib/api";

type Source = {
  span: { text: string; kind: string };
  document: { url: string | null; published_at: string | null; retrieved_at: string };
};

export function EvidenceDrawer({ evidence, calculations }: { evidence: Evidence[]; calculations: Calculation[] }) {
  const [open, setOpen] = useState<Record<string, Source>>({});

  async function show(id: string) {
    if (open[id]) return;
    const source = await api<Source>(`evidence/${id}`);
    setOpen((current) => ({ ...current, [id]: source }));
  }

  return (
    <section aria-label="Evidence">
      <h3>Evidence</h3>
      {evidence.map((item) => (
        <div key={item.id}>
          <blockquote>{item.quote}</blockquote>
          <p>{item.relationship}; {item.origin}
            {!item.comparable && `; not directly comparable (${item.differences.join(", ")})`}
            {" "}<button className="link" onClick={() => show(item.id)}>Show source passage</button></p>
          {open[item.id] && (
            <p>{open[item.id].span.text}<br />
              Source: {open[item.id].document.url ?? "uploaded document"}. Published:{" "}
              {open[item.id].document.published_at ?? "unknown"}. Retrieved:{" "}
              {open[item.id].document.retrieved_at}.</p>
          )}
        </div>
      ))}
      {calculations.map((calc) => (
        <div key={calc.id}>
          <strong>Calculation</strong> {calc.note}
          <ul>
            {calc.steps.map((step) => (
              <li key={step.out}>{step.out} = {step.op}({step.args.join(", ")}) ={" "}
                {Number(calc.outputs[step.out])} {calc.units[step.out]}</li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
}
