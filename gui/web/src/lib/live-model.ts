// SPDX-License-Identifier: Apache-2.0
// Pure helpers for presenting the live running-model detail across surfaces
// (top-bar chip, Overview KPI, Models badge, Chat/Clients header).
import type { EngineModelDetail, EngineModelInfo } from "../api";

/** The primary served model of a reachable engine (engines almost always serve
 *  one), or null when nothing is running. */
export function firstModel(detail?: EngineModelDetail | null): EngineModelInfo | null {
  if (!detail?.reachable) return null;
  return detail.models?.[0] ?? null;
}

/** The served-model id of the running engine, or null. */
export function liveModelName(detail?: EngineModelDetail | null): string | null {
  return firstModel(detail)?.id ?? null;
}

/** Human context-window label from a max_model_len: 131072 → "128K", 8192 → "8K". */
export function fmtCtx(maxLen?: number | null): string | null {
  if (!maxLen || maxLen <= 0) return null;
  return maxLen >= 1024 ? `${Math.round(maxLen / 1024)}K` : String(maxLen);
}

/** True when the given catalog model id is the one currently being served. */
export function isModelLive(detail: EngineModelDetail | null | undefined, catalogModelId: string): boolean {
  if (!detail?.reachable) return false;
  return (detail.models ?? []).some((m) => m.catalog?.model_id === catalogModelId);
}
