// SPDX-License-Identifier: Apache-2.0
// Preset section panels: operator-local user presets + profile-delta inspector.
import { type UserPresetList } from "../api";
import { tr } from "../i18n";

export function UserPresetsPanel({ presets }: { presets: UserPresetList | null }) {
  const rows = presets?.presets ?? [];
  return (
    <div className="config-item-inspector">
      <strong>{tr("User presets")} ({presets?.count ?? 0})</strong>
      <span>{tr("operator-local config dir")}</span>
      {rows.length === 0 ? (
        <p className="muted">{tr("No operator-local presets yet. Apply a draft to create one.")}</p>
      ) : (
        rows.map((preset) => (
          <p key={preset.id}>
            <em>{preset.id}</em>
            <code>{preset.model ?? "?"}{preset.profile ? ` / ${preset.profile}` : ""}</code>
          </p>
        ))
      )}
    </div>
  );
}

export function ProfileDeltaPanel({ def }: { def: Record<string, any> }) {
  const delta = (def.patches_delta ?? {}) as Record<string, any>;
  const enable = (delta.enable ?? {}) as Record<string, string>;
  const disable = Array.isArray(delta.disable) ? delta.disable : [];
  const override = (delta.override ?? {}) as Record<string, string>;
  const sizing = def.sizing_override as Record<string, any> | null;
  return (
    <div className="config-item-inspector delta">
      <strong>{tr("Profile delta:")} {def.id}</strong>
      <span>{String(def.status ?? "experimental")} · {tr("role")} {String(def.role ?? "default")}</span>
      <p><em>{tr("enable")}</em><code>{Object.keys(enable).length}</code></p>
      <p><em>{tr("disable")}</em><code>{disable.length}</code></p>
      <p><em>{tr("override")}</em><code>{Object.keys(override).length}</code></p>
      <p><em>{tr("sizing override")}</em><code>{sizing ? tr("yes") : tr("no")}</code></p>
      {disable.length > 0 && (
        <p><em>{tr("disabled")}</em><code>{disable.map(String).join(", ")}</code></p>
      )}
    </div>
  );
}
