// SPDX-License-Identifier: Apache-2.0
// The Clients section: live engine status + playground, client endpoints, and
// copy-paste cURL/Python/streaming/health snippets for the served model on the
// selected runtime host. Extracted from section-workspace.tsx.
import {
  Activity, Box, Code2, KeyRound, Layers3, Link2, MessageSquare
} from "lucide-react";
import { tr } from "../i18n";
import { runtimeHost } from "../lib/overview-presenters";
import { targetTitle } from "../lib/format";
import type { RuntimeMode } from "../nav";
import type { ProductCapability } from "../api";
import type { GuiSettings } from "../settings";
import { ModuleCard, ModuleGrid } from "../components/layout";
import { CompactList, InfoRows } from "../components/primitives";
import { CodeTabs } from "../components/shell-bits";
import { EngineStatusCard, EnginePlayground } from "../lazy-panels";
import { LiveModelInline } from "../components/live-model";
import { EndpointRows } from "./rail-cards";

export function ClientsSection({
  runtimeMode,
  settings,
  composed,
  selectedPreset,
  runtimeTargets,
  runtimeTarget
}: {
  runtimeMode: RuntimeMode;
  settings: GuiSettings;
  composed: Record<string, unknown>;
  selectedPreset: string;
  runtimeTargets: ProductCapability[];
  runtimeTarget: string;
}) {
        const clientHost = runtimeHost(runtimeMode, settings.remoteHost);
        const baseUrl = `http://${clientHost}:8000/v1`;
        const modelName = String(composed.served_model_name ?? selectedPreset);
        return (
        <ModuleGrid>
          <ModuleCard title={tr("Live Engine")} icon={<Activity size={18} />} desc={tr("Is the runtime up? Loaded model and version from the running server.")} wide>
            <LiveModelInline host={clientHost} port={8000} />
            <EngineStatusCard />
          </ModuleCard>
          <ModuleCard title={tr("Playground")} icon={<MessageSquare size={18} />} desc={tr("Send a real prompt to the running engine — a one-click smoke test.")} wide>
            <EnginePlayground />
          </ModuleCard>
          <ModuleCard title={tr("Client Endpoints")} icon={<Link2 size={18} />} desc={tr("OpenAI-compatible API, health and metrics URLs for the selected runtime host.")} wide>
            <EndpointRows host={clientHost} />
          </ModuleCard>
          <ModuleCard title={tr("Quick Start")} icon={<Code2 size={18} />} desc={`${tr("Copy-paste clients for the served model")} "${modelName}".`} wide>
            <CodeTabs
              tabs={[
                {
                  id: "curl",
                  label: "cURL",
                  lines: [
                    `curl ${baseUrl}/chat/completions \\`,
                    `  -H "Content-Type: application/json" \\`,
                    `  -d '{`,
                    `    "model": "${modelName}",`,
                    `    "messages": [{"role": "user", "content": "Hello"}],`,
                    `    "max_tokens": 256`,
                    `  }'`
                  ]
                },
                {
                  id: "python",
                  label: "Python",
                  lines: [
                    "from openai import OpenAI",
                    "",
                    `client = OpenAI(base_url="${baseUrl}", api_key="not-needed")`,
                    "resp = client.chat.completions.create(",
                    `    model="${modelName}",`,
                    '    messages=[{"role": "user", "content": "Hello"}],',
                    "    max_tokens=256,",
                    ")",
                    "print(resp.choices[0].message.content)"
                  ]
                },
                {
                  id: "stream",
                  label: tr("Streaming"),
                  lines: [
                    "from openai import OpenAI",
                    "",
                    `client = OpenAI(base_url="${baseUrl}", api_key="not-needed")`,
                    "stream = client.chat.completions.create(",
                    `    model="${modelName}",`,
                    '    messages=[{"role": "user", "content": "Hello"}],',
                    "    stream=True,",
                    ")",
                    "for chunk in stream:",
                    "    delta = chunk.choices[0].delta.content or \"\"",
                    "    print(delta, end=\"\", flush=True)"
                  ]
                },
                {
                  id: "health",
                  label: tr("Health"),
                  lines: [
                    `curl http://${clientHost}:8000/health`,
                    `curl http://${clientHost}:8001/metrics | grep vllm:`,
                    `curl ${baseUrl}/models`
                  ]
                }
              ]}
            />
          </ModuleCard>
          <ModuleCard title={tr("Served Model")} icon={<Box size={18} />} desc={tr("What the OpenAI-compatible server exposes for this preset.")}>
            <InfoRows
              rows={[
                [tr("Model name"), modelName],
                [tr("Base URL"), baseUrl],
                [tr("Runtime target"), targetTitle(runtimeTargets, runtimeTarget)],
                [tr("Host mode"), runtimeMode === "remote" ? tr("Remote host") : tr("Local server")]
              ]}
            />
          </ModuleCard>
          <ModuleCard title={tr("Authentication")} icon={<KeyRound size={18} />} desc={tr("The Product API token; the inference server itself follows your vLLM launch flags.")}>
            <InfoRows
              rows={[
                ["GUI/Product API", tr("Open by default; set SNDR_GUI_TOKEN to require a bearer token")],
                [tr("Header"), "Authorization: Bearer <token> or X-SNDR-Token: <token>"],
                [tr("Inference API key"), tr('OpenAI clients accept any value (e.g. "not-needed") unless vLLM --api-key is set')]
              ]}
            />
          </ModuleCard>
          <ModuleCard title={tr("Client Modes")} icon={<Layers3 size={18} />} desc={tr("How operators reach this control plane.")}>
            <CompactList rows={[[tr("Web UI"), tr("Browser control center")], [tr("Desktop"), tr("Tauri remote shell")], ["API", tr("OpenAI-compatible endpoint")], ["CLI", tr("Operator mirror")]]} />
          </ModuleCard>
        </ModuleGrid>
        );
}
