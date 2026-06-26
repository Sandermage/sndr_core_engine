// SPDX-License-Identifier: Apache-2.0
// Element field schema + editor: the curated per-kind field specs, adaptive
// discovery of extra scalar fields, grouping, per-field validation and the
// ElementField input dispatcher. Shared by LayerEditor and ConfigElementEditor.
import { AlertTriangle } from "lucide-react";
import { tr } from "../i18n";
import { TextField, NumberField, BoolField, SelectField } from "../components/form-fields";

export type ElementKind = "model" | "hardware" | "profile" | "preset";
export type FieldSpec = {
  path: string;
  label: string;
  type: "text" | "number" | "select" | "bool";
  options?: string[];
  group?: string;
  hint?: string;
};

// Returns the curated field specs with translated labels/hints/groups. A
// function (not a const) so labels re-resolve through `tr()` on language switch.
export function ELEMENT_FIELDS_FOR(kind: ElementKind): FieldSpec[] {
  const all: Record<ElementKind, FieldSpec[]> = {
    model: [
      { path: "title", label: tr("Title"), type: "text", group: tr("Identity") },
      { path: "served_model_name", label: tr("Served name"), type: "text", group: tr("Identity") },
      { path: "model_path", label: tr("Model path"), type: "text", group: tr("Identity"), hint: tr("Container/host checkpoint path") },
      { path: "maintainer", label: tr("Maintainer"), type: "text", group: tr("Identity") },
      { path: "license", label: tr("License"), type: "text", group: tr("Identity") },
      { path: "last_validated", label: tr("Last validated"), type: "text", group: tr("Identity") },
      { path: "dtype", label: tr("Dtype"), type: "select", options: ["float16", "bfloat16", "float32"], group: tr("Precision") },
      { path: "quantization", label: tr("Quantization"), type: "text", group: tr("Precision") },
      { path: "trust_remote_code", label: tr("Trust remote code"), type: "bool", group: tr("Precision") },
      { path: "capabilities.attention_arch", label: tr("Attention arch"), type: "select", options: ["dense", "hybrid_gdn_moe", "hybrid_mamba", "moe", "gemma4_dense", "gemma4_moe"], group: tr("Capabilities") },
      { path: "capabilities.kv_cache_dtype", label: tr("KV cache dtype"), type: "select", options: ["auto", "fp8", "turboquant_k8v4", "turboquant_k8v8", "int8"], group: tr("Capabilities") },
      { path: "capabilities.tool_call_parser", label: tr("Tool parser"), type: "text", group: tr("Capabilities") },
      { path: "capabilities.reasoning_parser", label: tr("Reasoning parser"), type: "text", group: tr("Capabilities") },
      { path: "capabilities.enable_auto_tool_choice", label: tr("Auto tool choice"), type: "bool", group: tr("Capabilities") },
      { path: "capabilities.spec_decode.method", label: tr("Spec method"), type: "select", options: ["mtp", "ngram", "eagle"], group: tr("Speculative decode") },
      { path: "capabilities.spec_decode.num_speculative_tokens", label: tr("Spec K"), type: "number", group: tr("Speculative decode") },
      { path: "requires.min_gpu_count", label: tr("Min GPUs"), type: "number", group: tr("Requirements") },
      { path: "requires.min_total_vram_mib", label: tr("Min VRAM (MiB)"), type: "number", group: tr("Requirements") },
      { path: "versions.genesis_pin_min", label: tr("Genesis pin (min)"), type: "text", group: tr("Version pins") },
      { path: "versions.vllm_pin_required", label: tr("vLLM pin required"), type: "text", group: tr("Version pins") },
      { path: "versions.reference_metrics_ref", label: tr("Reference metrics ref"), type: "text", group: tr("Version pins") }
    ],
    hardware: [
      { path: "title", label: tr("Title"), type: "text", group: tr("Identity") },
      { path: "maintainer", label: tr("Maintainer"), type: "text", group: tr("Identity") },
      { path: "hardware.n_gpus", label: tr("GPU count"), type: "number", group: tr("GPU") },
      { path: "hardware.min_vram_per_gpu_mib", label: tr("Min VRAM/GPU (MiB)"), type: "number", group: tr("GPU") },
      { path: "hardware.cuda_capability_min", label: tr("CUDA cap min"), type: "text", group: tr("GPU"), hint: tr("e.g. 8.6 (Ampere)") },
      { path: "sizing.max_model_len", label: tr("Max context"), type: "number", group: tr("Sizing") },
      { path: "sizing.max_num_seqs", label: tr("Max sequences"), type: "number", group: tr("Sizing") },
      { path: "sizing.max_num_batched_tokens", label: tr("Max batched tokens"), type: "number", group: tr("Sizing") },
      { path: "sizing.gpu_memory_utilization", label: tr("GPU mem util"), type: "number", group: tr("Sizing") },
      { path: "sizing.enable_chunked_prefill", label: tr("Chunked prefill"), type: "bool", group: tr("Sizing") },
      { path: "sizing.enforce_eager", label: tr("Enforce eager"), type: "bool", group: tr("Sizing") },
      { path: "sizing.disable_custom_all_reduce", label: tr("Disable custom all-reduce"), type: "bool", group: tr("Sizing") },
      { path: "runtime.default", label: tr("Default runtime"), type: "select", options: ["docker", "podman", "bare-metal"], group: tr("Runtime") }
    ],
    profile: [
      { path: "parent_model", label: tr("Parent model"), type: "text", group: tr("Identity") },
      { path: "status", label: tr("Status"), type: "select", options: ["experimental", "validated", "promoted"], group: tr("Identity") },
      { path: "role", label: tr("Role"), type: "select", options: ["default", "structured", "gateway", "bench", "dev", "qa", "diagnostic"], group: tr("Identity") },
      { path: "created", label: tr("Created"), type: "text", group: tr("Identity") },
      { path: "sizing_override.max_model_len", label: tr("Max context"), type: "number", group: tr("Sizing override"), hint: tr("Leave empty to inherit hardware") },
      { path: "sizing_override.max_num_seqs", label: tr("Max sequences"), type: "number", group: tr("Sizing override") },
      { path: "sizing_override.max_num_batched_tokens", label: tr("Max batched tokens"), type: "number", group: tr("Sizing override") },
      { path: "sizing_override.gpu_memory_utilization", label: tr("GPU mem util"), type: "number", group: tr("Sizing override") },
      { path: "sizing_override.enforce_eager", label: tr("Enforce eager"), type: "bool", group: tr("Sizing override") },
      { path: "versions_override.vllm_pin_required", label: tr("vLLM pin required"), type: "text", group: tr("Version override") },
      { path: "versions_override.genesis_pin", label: tr("Genesis pin"), type: "text", group: tr("Version override") },
      { path: "promotion.promote_to", label: tr("Promote to"), type: "text", group: tr("Promotion") },
      { path: "promotion.notes", label: tr("Promotion notes"), type: "text", group: tr("Promotion") }
    ],
    preset: [
      { path: "model", label: tr("Model"), type: "text", group: tr("Composition") },
      { path: "hardware", label: tr("Hardware"), type: "text", group: tr("Composition") },
      { path: "profile", label: tr("Profile"), type: "text", group: tr("Composition") },
      { path: "runtime", label: tr("Runtime"), type: "select", options: ["docker", "podman", "kubernetes", "systemd", "bare-metal"], group: tr("Composition") },
      { path: "card.title", label: tr("Card title"), type: "text", group: tr("Card") },
      { path: "card.summary", label: tr("Summary"), type: "text", group: tr("Card") },
      { path: "card.status", label: tr("Card status"), type: "select", options: ["experimental", "production_candidate", "production"], group: tr("Card") },
      { path: "card.mode", label: tr("Mode"), type: "text", group: tr("Card") },
      { path: "card.audience", label: tr("Audience"), type: "select", options: ["operator", "developer", "internal"], group: tr("Card") },
      { path: "card.evidence_visibility", label: tr("Evidence visibility"), type: "select", options: ["public", "private", "mixed"], group: tr("Card") },
      { path: "card.fallback_preset", label: tr("Fallback preset"), type: "text", group: tr("Card") }
    ]
  };
  return all[kind];
}

// Top-level keys excluded from auto-discovery: structural, noisy, or shown
// elsewhere (patch matrix), or arrays/dicts that need bespoke editors.
const _AUTO_EXCLUDE = new Set([
  "patches", "patches_attribution", "notes", "schema_version", "kind", "id",
  "patches_delta", "system_env"
]);

function _isScalar(v: any): boolean {
  return v === null || ["string", "number", "boolean"].includes(typeof v);
}

// Adaptive discovery: walk the loaded definition and surface every scalar leaf
// that the curated schema does not already cover, so the editor reflects
// whatever fields a given model/hardware/profile/preset actually contains.
export function discoverExtraFields(obj: any, known: Set<string>): FieldSpec[] {
  const out: FieldSpec[] = [];
  const walk = (node: any, prefix: string): void => {
    if (!node || typeof node !== "object" || Array.isArray(node)) return;
    for (const [key, value] of Object.entries(node)) {
      const path = prefix ? `${prefix}.${key}` : key;
      if (!prefix && _AUTO_EXCLUDE.has(key)) continue;
      if (_isScalar(value)) {
        if (!known.has(path)) {
          const type = typeof value === "boolean" ? "bool" : typeof value === "number" ? "number" : "text";
          out.push({ path, label: key, type, group: prefix ? `${tr("More")} · ${prefix}` : tr("More") });
        }
      } else if (value && typeof value === "object" && !Array.isArray(value)) {
        walk(value, path);
      }
      // arrays / arrays-of-objects are left to the YAML panel (bespoke shape)
    }
  };
  walk(obj, "");
  return out;
}

export function groupFields(fields: FieldSpec[]): Array<[string, FieldSpec[]]> {
  const order: string[] = [];
  const byGroup = new Map<string, FieldSpec[]>();
  for (const spec of fields) {
    const group = spec.group ?? "";
    if (!byGroup.has(group)) { byGroup.set(group, []); order.push(group); }
    byGroup.get(group)!.push(spec);
  }
  return order.map((group) => [group, byGroup.get(group)!]);
}

// Live sanity-check for the most error-prone numeric config fields — catches a
// bad value (e.g. gpu_memory_utilization 1.5) before it's saved/applied.
function fieldWarning(spec: FieldSpec, value: any): string | null {
  if (value == null || value === "" || spec.type !== "number") return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return tr("not a number");
  const leaf = spec.path.split(".").pop();
  switch (leaf) {
    case "gpu_memory_utilization": return n > 0 && n <= 1 ? null : tr("expected 0 < util ≤ 1");
    case "max_num_seqs": return Number.isInteger(n) && n >= 1 && n <= 4096 ? null : tr("expected 1–4096");
    case "max_num_batched_tokens": return n >= 256 ? null : tr("expected ≥ 256");
    case "max_model_len": return n >= 256 ? null : tr("expected ≥ 256");
    case "num_speculative_tokens": return n >= 0 && n <= 16 ? null : tr("expected 0–16");
    case "n_gpus":
    case "min_gpu_count": return Number.isInteger(n) && n >= 1 && n <= 8 ? null : tr("expected 1–8");
    default: return n < 0 ? tr("must be ≥ 0") : null;
  }
}

export function ElementField({ spec, value, onChange }: { spec: FieldSpec; value: any; onChange: (value: any) => void }) {
  const warn = fieldWarning(spec, value);
  const field = (() => {
    if (spec.type === "bool") {
      return <BoolField label={spec.label} value={Boolean(value)} onChange={onChange} />;
    }
    if (spec.type === "number") {
      return <NumberField label={spec.label} value={typeof value === "number" ? value : Number(value) || 0} onChange={onChange} />;
    }
    if (spec.type === "select") {
      const current = value == null ? "" : String(value);
      const options = spec.options ?? [];
      const merged = current && !options.includes(current) ? [current, ...options] : options;
      return <SelectField label={spec.label} value={current} options={merged} onChange={onChange} />;
    }
    return <TextField label={spec.label} value={value == null ? "" : String(value)} onChange={onChange} />;
  })();
  if (!spec.hint && !warn) return field;
  return (
    <div className={`element-field-hinted${warn ? " invalid" : ""}`}>
      {field}
      {warn
        ? <small className="element-field-warn"><AlertTriangle size={11} /> {warn}</small>
        : spec.hint ? <small className="element-field-hint">{spec.hint}</small> : null}
    </div>
  );
}

