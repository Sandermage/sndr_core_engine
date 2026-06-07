// SPDX-License-Identifier: Apache-2.0
// Pure display-formatting helpers shared across panels. Extracted from App.tsx
// (modularization) with no behavior change.
import { asRecord } from "./coerce";

/** Flatten a patch `applies_to` record into label/value rows for display. */
export function formatAppliesTo(applies: unknown): Array<[string, string]> {
  const record = asRecord(applies);
  const rows: Array<[string, string]> = [];
  for (const [key, value] of Object.entries(record)) {
    const text = Array.isArray(value) ? value.join(", ") : String(value);
    if (key === "is_turboquant") rows.push(["TurboQuant models", text === "true" || text === "True" ? "required" : text]);
    else if (key === "vllm_version_range") rows.push(["vLLM version", Array.isArray(value) ? value.join("  ") : text]);
    else rows.push([key.replace(/_/g, " "), text]);
  }
  return rows;
}

/** Render an arbitrary param value: em-dash for empty, locale number, else string. */
export function fmtParam(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "number") return value.toLocaleString("en-US");
  return String(value);
}

/** Short workload label for compact chips (free_chat → "chat", ...). */
export function shortWorkload(value: string): string {
  const labels: Record<string, string> = {
    free_chat: "chat",
    code_gen: "code",
    "tool_call.short": "tool",
    "tool_call.long": "tool+",
    "structured_json.short": "json",
    "structured_json.long": "json+",
    summarization: "sum",
  };
  return labels[value] ?? value.replace(/.*[_.]/, "").slice(0, 6);
}

/** Compact token count: 1500 → "2K", 0 → "-". */
export function formatTokens(value: number): string {
  if (!value) return "-";
  if (value >= 1000) return `${Math.round(value / 1000)}K`;
  return String(value);
}

/** VRAM in MiB → "X.Y GB · N MiB", or "-" for non-positive/invalid. */
export function formatVram(value: unknown): string {
  const mib = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(mib) || mib <= 0) return "-";
  return `${(mib / 1024).toFixed(1)} GB · ${mib.toLocaleString()} MiB`;
}

/** Sum a per-GPU VRAM array (MiB) into whole GiB; 0 for an empty list. */
export function totalVramGiB(vram: number[]): number {
  return vram.length ? Math.round(vram.reduce((acc, value) => acc + (value || 0), 0) / 1024) : 0;
}

/** Resolve a runtime-target id to its display title, falling back to the id. */
export function targetTitle(targets: Array<{ id: string; title: string }>, id: string): string {
  return targets.find((target) => target.id === id)?.title ?? id;
}
