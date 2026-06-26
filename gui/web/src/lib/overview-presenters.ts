// SPDX-License-Identifier: Apache-2.0
// Presentation helpers for the overview / launch workspace: activity-feed rows
// (synthetic status lines merged with real backend events), the read-only
// CLI-mirror lines, and runtime-mode host resolution. Pure functions, kept out
// of App.tsx so the shell stays focused on composition.
import { tr } from "../i18n";
import type { RuntimeMode } from "../nav";
import { DEFAULT_REMOTE_HOST } from "../settings";
import type { RecommendForm } from "../recommend";
import type { FetchState } from "../hooks/useApiQuery";
import type { BackendEvent } from "../api";

export function buildEvents({
  state,
  error,
  selectedPreset,
  runtimeTarget,
  visibility,
  live = []
}: {
  state: FetchState;
  error: string | null;
  selectedPreset: string;
  runtimeTarget: string;
  visibility: string;
  live?: BackendEvent[];
}): Array<[string, string, string]> {
  const now = new Date();
  const stamp = (offset: number) =>
    new Date(now.getTime() - offset * 60_000).toLocaleTimeString([], {
      hour: "2-digit",
      minute: "2-digit"
    });
  const rows: Array<[string, string, string]> = [
    [stamp(0), state === "error" ? "error" : "info", state === "loading" ? tr("Refreshing Product API snapshot...") : `${tr("Selected preset")} ${selectedPreset}`],
    [stamp(2), "info", `${tr("Runtime target set to")} ${runtimeTarget}`],
    [stamp(4), visibility === "public" ? "info" : "warn", `${tr("Evidence visibility")}: ${visibility}`],
    [stamp(6), "info", tr("Catalog and capability surfaces loaded through typed Product API")]
  ];
  if (error) rows.unshift([stamp(0), "error", error]);
  // Real backend events (dry-run jobs, lifecycle) take precedence at the top.
  const liveRows: Array<[string, string, string]> = live
    .slice(-12)
    .reverse()
    .map((event) => {
      const time = new Date(event.ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
      const tone = event.kind === "error" ? "error" : event.kind === "job" ? "ok" : "info";
      return [time, tone, event.message];
    });
  return [...liveRows, ...rows];
}

export function buildCliMirror({
  selectedPreset,
  runtimeTarget,
  patchPolicy,
  recommendForm,
  apiBase
}: {
  selectedPreset: string;
  runtimeTarget: string;
  patchPolicy: string;
  recommendForm: RecommendForm;
  apiBase: string;
}) {
  return [
    `$ sndr preset recommend --workload ${recommendForm.workload} --hardware ${recommendForm.hardware} --concurrency ${recommendForm.concurrency}${recommendForm.preferPublic ? " --prefer-public-evidence" : ""}`,
    `$ sndr preset explain ${selectedPreset}`,
    `$ sndr launch plan --preset ${selectedPreset} --runtime-target ${runtimeTarget} --patch-policy ${patchPolicy} --dry-run`,
    `$ sndr doctor --host current --all`,
    `$ curl ${apiBase}/api/v1/health`
  ];
}

export function runtimeHost(mode: RuntimeMode, remoteHost: string = DEFAULT_REMOTE_HOST) {
  return mode === "remote" ? (remoteHost.trim() || DEFAULT_REMOTE_HOST) : "127.0.0.1";
}
