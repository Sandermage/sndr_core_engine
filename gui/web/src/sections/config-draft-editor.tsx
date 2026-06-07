// SPDX-License-Identifier: Apache-2.0
// Runtime config draft editor: live sliders/toggles for sizing, spec-decode and
// KV/runtime, with a pending-changes diff and a YAML preview. Extracted from
// App.tsx (modularization).
//
// Enterprise touch over the inline original (classes unchanged): the Collapsible
// disclosure now wires aria-controls -> body id (useId) for WCAG conformance.
import { useEffect, useId, useMemo, useState, type ReactNode } from "react";
import { Copy, ChevronRight } from "lucide-react";
import { CodeBlock } from "../components/code-block";
import { BoolField, SelectField } from "../components/form-fields";
import { type RuntimeConfigDraft, buildRuntimeDraft, buildDraftYaml, runtimeDraftDiff } from "../lib/runtime-draft";

function Collapsible({
  title,
  subtitle,
  right,
  defaultOpen = true,
  children
}: {
  title: string;
  subtitle?: string;
  right?: number;
  defaultOpen?: boolean;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const bodyId = useId();
  return (
    <section className={`collapsible ${open ? "open" : ""}`}>
      <button className="collapsible-head" onClick={() => setOpen((value) => !value)} aria-expanded={open} aria-controls={bodyId}>
        <ChevronRight className="coll-caret" size={15} />
        <strong>{title}</strong>
        {subtitle && <span>{subtitle}</span>}
        {right ? <em className="coll-badge">{right} changed</em> : null}
      </button>
      {open && <div className="collapsible-body" id={bodyId}>{children}</div>}
    </section>
  );
}

function DraftControl({
  label,
  value,
  min,
  max,
  step,
  suffix = "",
  onChange
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  suffix?: string;
  onChange: (value: number) => void;
}) {
  return (
    <label className="config-field">
      <span>{label}</span>
      <div className="range-row">
        <input
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        <input
          type="number"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(event) => onChange(Number(event.target.value))}
        />
        {suffix && <em>{suffix}</em>}
      </div>
    </label>
  );
}

export function ParamFields({
  baseDraft,
  draft,
  set
}: {
  baseDraft: RuntimeConfigDraft;
  draft: RuntimeConfigDraft;
  set: (patch: Partial<RuntimeConfigDraft>) => void;
}) {
  const changed = (...keys: Array<keyof RuntimeConfigDraft>) =>
    keys.filter((key) => baseDraft[key] !== draft[key]).length;
  return (
    <>
      <Collapsible
        title="Sizing & memory"
        subtitle="context, batching, GPU memory"
        right={changed("max_model_len", "max_num_seqs", "max_num_batched_tokens", "gpu_memory_utilization", "enable_chunked_prefill", "enforce_eager", "disable_custom_all_reduce") || undefined}
      >
        <div className="param-grid">
          <DraftControl label="Max context" value={draft.max_model_len} min={4096} max={1048576} step={4096} onChange={(value) => set({ max_model_len: value })} />
          <DraftControl label="Max sequences" value={draft.max_num_seqs} min={1} max={256} step={1} onChange={(value) => set({ max_num_seqs: value })} />
          <DraftControl label="Max batched tokens" value={draft.max_num_batched_tokens} min={512} max={32768} step={512} onChange={(value) => set({ max_num_batched_tokens: value })} />
          <DraftControl label="GPU memory" value={Math.round(draft.gpu_memory_utilization * 100)} min={40} max={98} step={1} suffix="%" onChange={(value) => set({ gpu_memory_utilization: value / 100 })} />
        </div>
        <div className="param-toggles">
          <BoolField label="Chunked prefill" value={draft.enable_chunked_prefill} onChange={(value) => set({ enable_chunked_prefill: value })} />
          <BoolField label="Enforce eager" value={draft.enforce_eager} onChange={(value) => set({ enforce_eager: value })} />
          <BoolField label="Disable custom all-reduce" value={draft.disable_custom_all_reduce} onChange={(value) => set({ disable_custom_all_reduce: value })} />
        </div>
      </Collapsible>

      <Collapsible title="Speculative decode" subtitle="draft method and depth" right={changed("spec_decode_method", "spec_decode_K") || undefined}>
        <div className="param-grid">
          <SelectField label="Method" value={draft.spec_decode_method} options={["none", "mtp", "ngram", "eagle"]} onChange={(value) => set({ spec_decode_method: value })} />
          <DraftControl label="Num spec tokens (K)" value={draft.spec_decode_K} min={0} max={8} step={1} onChange={(value) => set({ spec_decode_K: value })} />
        </div>
      </Collapsible>

      <Collapsible title="KV cache & runtime" subtitle="cache dtype, target, patch policy" right={changed("kv_cache_dtype", "runtime_target", "patch_policy") || undefined}>
        <div className="param-grid">
          <SelectField label="KV cache dtype" value={draft.kv_cache_dtype} options={["auto", "fp8", "turboquant_k8v4", "turboquant_k8v8", "int8"]} onChange={(value) => set({ kv_cache_dtype: value })} />
          <SelectField label="Runtime target" value={draft.runtime_target} options={["docker", "docker_compose", "podman", "kubernetes", "systemd", "bare-metal"]} onChange={(value) => set({ runtime_target: value })} />
        </div>
        <div className="param-field">
          <span>Patch policy</span>
          <div className="settings-segmented" role="group" aria-label="Patch policy">
            {["compact", "safe", "minimal"].map((policy) => (
              <button key={policy} className={draft.patch_policy === policy ? "active" : ""} aria-pressed={draft.patch_policy === policy} onClick={() => set({ patch_policy: policy })}>{policy}</button>
            ))}
          </div>
        </div>
      </Collapsible>
    </>
  );
}

export function ConfigDraftEditor({
  selectedPreset,
  composed,
  runtimeTarget,
  patchPolicy
}: {
  selectedPreset: string;
  composed: Record<string, unknown>;
  runtimeTarget: string;
  patchPolicy: string;
}) {
  const baseDraft = useMemo(
    () => buildRuntimeDraft(composed, runtimeTarget, patchPolicy),
    [composed, runtimeTarget, patchPolicy]
  );
  const [draft, setDraft] = useState<RuntimeConfigDraft>(baseDraft);

  useEffect(() => {
    setDraft(baseDraft);
  }, [baseDraft, selectedPreset]);

  const diffs = runtimeDraftDiff(baseDraft, draft);
  const previewLines = buildDraftYaml(selectedPreset, draft);
  const set = (patch: Partial<RuntimeConfigDraft>) => setDraft((current) => ({ ...current, ...patch }));

  return (
    <div className="param-editor">
      <div className="param-editor-controls">
        <ParamFields baseDraft={baseDraft} draft={draft} set={set} />
      </div>

      <div className="param-editor-preview">
        <div className="diff-panel">
          <strong>Pending changes ({diffs.length})</strong>
          {diffs.length ? diffs.map((diff, index) => <span key={index}>{diff}</span>) : <span>No changes vs composed baseline</span>}
        </div>
        <CodeBlock lines={previewLines} />
        <div className="config-actions">
          <span className="config-actions-note">Persist via Configs → Apply Plan</span>
          <button className="ghost-button" onClick={() => setDraft(baseDraft)}>Reset</button>
          <button className="ghost-button" onClick={() => void navigator.clipboard?.writeText(previewLines.join("\n"))}>
            <Copy size={14} /> Copy YAML
          </button>
        </div>
      </div>
    </div>
  );
}
