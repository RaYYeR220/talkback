"use client";

import { useRef, type KeyboardEvent } from "react";
import { OUTPUTS, TERRITORY } from "@/lib/territories";
import type { Output } from "@/lib/types";

/** A radio group of program outputs (roving focus, arrow keys move and select). */
export function OutputSwitch({
  value,
  onChange,
  outputs = OUTPUTS,
  label = "Program output",
}: {
  value: Output;
  onChange: (o: Output) => void;
  outputs?: Output[];
  label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  const onKey = (e: KeyboardEvent) => {
    const i = outputs.indexOf(value);
    let next: Output | null = null;
    if (e.key === "ArrowRight" || e.key === "ArrowDown") next = outputs[(i + 1) % outputs.length];
    if (e.key === "ArrowLeft" || e.key === "ArrowUp") next = outputs[(i - 1 + outputs.length) % outputs.length];
    if (!next) return;
    e.preventDefault();
    onChange(next);
    const target = next;
    requestAnimationFrame(() => ref.current?.querySelector<HTMLButtonElement>(`[data-output="${target}"]`)?.focus());
  };

  return (
    <div className="segmented" role="radiogroup" aria-label={label} ref={ref}>
      {outputs.map((o) => (
        <button
          key={o}
          type="button"
          role="radio"
          data-output={o}
          aria-checked={value === o}
          title={`${TERRITORY[o].label} · ${TERRITORY[o].language}`}
          onClick={() => onChange(o)}
          onKeyDown={onKey}
          tabIndex={value === o ? 0 : -1}
        >
          {TERRITORY[o].code}
        </button>
      ))}
    </div>
  );
}
