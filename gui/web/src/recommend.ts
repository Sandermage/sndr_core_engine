// SPDX-License-Identifier: Apache-2.0
// Shared recommend-form vocabulary: the form shape, its defaults, and the
// catalogue of selectable workloads. Lives outside App.tsx so the recommend
// panel and the app shell share one source of truth.

export type RecommendForm = {
  workload: string;
  hardware: string;
  concurrency: number;
  top: number;
  preferPublic: boolean;
};

export const defaultRecommend: RecommendForm = {
  workload: "free_chat",
  hardware: "a5000-2x-24gbvram-16cpu-128gbram",
  concurrency: 8,
  top: 5,
  preferPublic: true
};

export const workloadChoices = [
  { id: "free_chat", label: "Free chat" },
  { id: "code_gen", label: "Code gen" },
  { id: "tool_call.short", label: "Tool calls" },
  { id: "structured_json.short", label: "Structured JSON" },
  { id: "summarization", label: "Summarization" },
  { id: "long_context_qa", label: "Long context" }
];
