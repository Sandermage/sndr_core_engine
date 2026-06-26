// SPDX-License-Identifier: Apache-2.0
// The Setup section: a logically-ordered first-run flow — orient (guided
// checklist) -> install the daemon/engine onto a host over SSH -> render deploy
// artifacts for a model. Owns its controlled tab state so "Set up as node" can
// jump straight to Install. Extracted from section-workspace.tsx.
import { useEffect, useState } from "react";
import { Rocket, Server, ShieldCheck } from "lucide-react";
import { tr } from "../i18n";
import type { EnvironmentReport, ProductOverview, DoctorReport, PresetListResult } from "../api";
import type { RuntimeMode, SectionId } from "../nav";
import type { GateStatus } from "../components/primitives";
import { TabbedSection } from "../components/tabbed-section";
import { TabIntro } from "../components/shell-bits";
import { InstallWizard, DeploymentConsole } from "../lazy-panels";
import { SetupWizard } from "./setup-wizard";

export function SetupSection({
  environment,
  overview,
  doctorReport,
  gateCounts,
  selectedPreset,
  runtimeMode,
  apiBase,
  installIntent,
  presets,
  onSection,
  onPreset
}: {
  environment: EnvironmentReport | null;
  overview: ProductOverview | null;
  doctorReport: DoctorReport | null;
  gateCounts: Record<GateStatus, number>;
  selectedPreset: string;
  runtimeMode: RuntimeMode;
  apiBase: string;
  installIntent: { hostId?: string; target?: string } | null;
  presets: PresetListResult | null;
  onSection: (section: SectionId) => void;
  onPreset: (id: string) => void;
}) {
  // Default to the guided entry point; jump to Install when a node-setup intent
  // arrives (the bug was a controlled tab with no change handler — it got stuck).
  const [setupTab, setSetupTab] = useState("guided");
  useEffect(() => { if (installIntent) setSetupTab("install"); }, [installIntent]);
  return (
            <TabbedSection
          id="setup"
          activeTab={setupTab}
          onTabChange={setSetupTab}
          tabs={[
            // 1) Orient: where you are + what to do next (read-only, safe).
            {
              id: "guided",
              label: `1 · ${tr("Guided setup")}`,
              icon: <ShieldCheck size={15} />,
              render: () => (
                <>
                  <TabIntro icon={<ShieldCheck size={16} />} title={tr("Start here — guided setup")}
                    text={tr("A read-only checklist of where you stand: environment, engine, dependencies and launch gates, with a clear next step. Nothing is changed here — it just tells you what to do.")} />
                  <SetupWizard
                    environment={environment}
                    overview={overview}
                    doctorReport={doctorReport}
                    gateCounts={gateCounts}
                    selectedPreset={selectedPreset}
                    runtimeMode={runtimeMode}
                    apiBase={apiBase}
                    onSection={onSection}
                  />
                </>
              )
            },
            // 2) Install the SNDR daemon / engine onto a GPU server over SSH.
            {
              id: "install",
              label: `2 · ${tr("Install onto host")}`,
              icon: <Server size={15} />,
              render: () => (
                <>
                  <TabIntro icon={<Server size={16} />} title={tr("Install onto a GPU host (over SSH)")}
                    text={tr("Pick a registered host and a preset, preview the exact install plan, then apply it over SSH — it ships the daemon/engine onto that server so the GUI can manage it. Gated: review the plan before it runs.")} />
                  <InstallWizard initial={installIntent || undefined} />
                </>
              )
            },
            // 3) Render deploy artifacts (compose/systemd/run) for a chosen model.
            {
              id: "deploy",
              label: `3 · ${tr("Deploy a model")}`,
              icon: <Rocket size={15} />,
              render: () => (
                <>
                  <TabIntro icon={<Rocket size={16} />} title={tr("Deploy a model preset")}
                    text={tr("Turn a preset into ready-to-run artifacts — docker-compose, systemd unit or a docker run line, with the right image, GPUs, ports and patch env baked in. Copy them to the host, or use Install above to push over SSH.")} />
                  <DeploymentConsole
                    presets={presets}
                    selectedPreset={selectedPreset}
                    onSelectPreset={onPreset}
                  />
                </>
              )
            }
          ]}
        />
  );
}
