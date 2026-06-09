import { useEffect, useState } from "react";
import { BadgeCheck, Box, KeyRound, Lock, Package, RefreshCw, ShieldCheck, ShieldX } from "lucide-react";
import { api, type LicenseStatus } from "./api";
import { tr } from "./i18n";

const STATUS_HELP: Record<string, string> = {
  no_package: tr("The commercial vllm.sndr_engine overlay is not installed."),
  no_key: tr("sndr_engine is installed but no license key was found (set SNDR_ENGINE_LICENSE_KEY or drop the key file)."),
  bad_signature: tr("The license token's Ed25519 signature did not verify."),
  bad_payload: tr("The license signature is valid but its payload failed the contract check."),
  expired: tr("The license token has expired."),
  version_mismatch: tr("The sndr_engine version is incompatible with this core."),
  licensed: tr("A valid signed license entitles the engine tier."),
  licensed_legacy: tr("A plain (unsigned) key is present — legacy entitlement."),
  override: tr("Engine tier is force-enabled via an operator override."),
};

type ExpiryState = "none" | "valid" | "soon" | "expired";
function expiryInfo(expires: string | null | undefined): { state: ExpiryState; days: number | null; label: string } {
  if (!expires) return { state: "none", days: null, label: tr("no expiry set") };
  const t = Date.parse(expires);
  if (Number.isNaN(t)) return { state: "none", days: null, label: String(expires) };
  const days = Math.floor((t - Date.now()) / 86_400_000);
  if (days < 0) return { state: "expired", days, label: `${tr("expired")} ${-days}${tr("d ago")}` };
  if (days <= 30) return { state: "soon", days, label: `${days}${tr("d remaining")}` };
  return { state: "valid", days, label: `${days}${tr("d remaining")}` };
}

export function LicensePanel() {
  const [data, setData] = useState<LicenseStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const load = () => { setLoading(true); api.license().then(setData).catch(() => setData(null)).finally(() => setLoading(false)); };
  useEffect(() => { load(); }, []);

  if (data && !data.available) {
    return <div className="lic-empty"><Lock size={20} /><strong>{tr("License layer unavailable")}</strong><span>{data.reason}</span></div>;
  }

  const tier = data?.tier ?? "—";
  const isEngine = data?.eligible === true;
  const eng = data?.engine;
  const lic = data?.license;
  const sig = lic?.signature_valid;

  return (
    <div className="lic">
      <div className="lic-head">
        <div className={`lic-tier ${isEngine ? "engine" : "community"}`}>
          {isEngine ? <BadgeCheck size={18} /> : <Box size={18} />}
          <div className="lic-tier-id">
            <strong>{isEngine ? tr("SNDR Engine") : tr("Community")} {tr("tier")}</strong>
            <span>{data?.core ?? tr("public (unlicensed)")}</span>
          </div>
          <span className={`lic-pill ${isEngine ? "ok" : ""}`}>{tier}</span>
        </div>
        <button className="ghost-button" onClick={load} disabled={loading}>
          {loading ? <RefreshCw size={14} className="spin" /> : <RefreshCw size={14} />} {tr("Recheck")}
        </button>
      </div>

      <div className="lic-grid">
        <div className="lic-card">
          <div className="lic-card-t"><Package size={13} /> {tr("sndr_engine overlay")}</div>
          <div className={`lic-row ${eng?.installed ? "ok" : "off"}`}>
            <span>{tr("Installed")}</span><strong>{eng?.installed ? `${tr("yes")}${eng.version ? ` · v${eng.version}` : ""}` : tr("no")}</strong>
          </div>
          <div className="lic-row"><span>{tr("Module")}</span><strong className="mono">{eng?.module ?? "—"}</strong></div>
          {!eng?.installed && <div className="lic-hint">{tr("Install the commercial")} <code>vllm-sndr-engine</code> {tr("package to unlock engine-tier kernels/patches.")}</div>}
        </div>

        <div className="lic-card">
          <div className="lic-card-t"><KeyRound size={13} /> {tr("License token")}</div>
          <div className="lic-row"><span>{tr("Subject")}</span><strong className="mono">{lic?.subject ?? "—"}</strong></div>
          <div className="lic-row"><span>{tr("Expires")}</span><strong className="mono">{lic?.expires ?? "—"}</strong></div>
          {(() => {
            const ei = expiryInfo(lic?.expires);
            if (ei.state === "none") return null;
            const pct = ei.days === null ? 0 : Math.max(2, Math.min(100, Math.round((ei.days / 365) * 100)));
            return (
              <div className={`lic-expiry ${ei.state}`}>
                <div className="lic-expiry-bar"><span style={{ width: `${ei.state === "expired" ? 100 : pct}%` }} /></div>
                <span className="lic-expiry-label">{ei.label}</span>
                {ei.state === "soon" && <span className="lic-hint">{tr("Renew the license token soon to keep the engine tier entitled.")}</span>}
                {ei.state === "expired" && <span className="lic-hint">{tr("Token expired — engine-tier patches are gated off until renewed.")}</span>}
              </div>
            );
          })()}
          <div className={`lic-row ${sig === true ? "ok" : sig === false ? "bad" : ""}`}>
            <span>{tr("Signature")}</span>
            <strong>{sig === true ? <><ShieldCheck size={12} /> {tr("valid")}</> : sig === false ? <><ShieldX size={12} /> {tr("invalid")}</> : "—"}</strong>
          </div>
        </div>

        <div className="lic-card">
          <div className="lic-card-t"><ShieldCheck size={13} /> {tr("Entitlement")}</div>
          <div className={`lic-row ${isEngine ? "ok" : "off"}`}><span>{tr("Engine tier")}</span><strong>{isEngine ? tr("enabled") : tr("locked")}</strong></div>
          <div className="lic-row"><span>{tr("Premium patches on")}</span><strong className="mono">{data?.premium_patches_enabled ?? 0}</strong></div>
          <div className="lic-row"><span>{tr("Engine-tier patches")}</span><strong className="mono">{data?.engine_tier_patches ?? 0}</strong></div>
        </div>
      </div>

      {data?.status && (
        <div className={`lic-status ${isEngine ? "ok" : "locked"}`}>
          <span className="lic-status-code">{data.status}</span>
          <span className="lic-status-msg">{STATUS_HELP[data.status] ?? data.reason}</span>
        </div>
      )}
    </div>
  );
}
