// SPDX-License-Identifier: Apache-2.0
// Settings tab panels: API token manager, notification/alert config, and
// appearance settings (theme/density/accent/detail/layers) with their small
// setting primitives. Extracted from App.tsx (modularization) with no behavior
// change.
import { useEffect, useState, type ReactNode } from "react";
import { AlertTriangle, Bell, KeyRound, Loader2, Palette, PanelLeft, Route, Rows3, Send, Settings, Sparkles, Trash2 } from "lucide-react";
import { api, type AlertConfig, type ApiTokenRecord, getApiToken, setApiToken } from "../api";
import { type GuiSettings, type ThemeMode, type DensityMode, type AccentMode, type DetailMode } from "../settings";
import { ConfirmDialog } from "../components/dialogs";
import { CopyButton } from "../components/code-block";
import { SkeletonLines } from "../Skeleton";
import { toast } from "../components/toast";
import { tr } from "../i18n";

// Managed personal-access tokens for programmatic / CI access to the Product API.
export function ApiTokenManager({ enabled }: { enabled: boolean }) {
  const [tokens, setTokens] = useState<ApiTokenRecord[] | null>(null);
  const [unavailable, setUnavailable] = useState(!enabled);
  const [label, setLabel] = useState("");
  const [created, setCreated] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  function load() {
    api.apiTokens().then((result) => { setTokens(result.tokens); setUnavailable(false); }).catch(() => setUnavailable(true));
  }
  // Only probe the protected endpoint when authenticated — avoids a benign 401.
  useEffect(() => { if (enabled) load(); else setUnavailable(true); }, [enabled]);
  async function create() {
    setBusy(true);
    try {
      const result = await api.apiTokenCreate(label.trim() || "api-token");
      setCreated(result.token);
      setLabel("");
      load();
      toast(tr("API token created"), "success");
    } catch {
      toast(tr("Failed to create token"), "error");
    } finally { setBusy(false); }
  }
  async function revoke(id: string) {
    try { await api.apiTokenRevoke(id); load(); toast(tr("Token revoked"), "success"); } catch { toast(tr("Failed to revoke token"), "error"); }
  }
  const [confirmRevoke, setConfirmRevoke] = useState<{ id: string; label: string } | null>(null);
  const stamp = (ts: number) => new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "2-digit", year: "numeric" });
  if (unavailable) {
    return <p className="muted">{tr("API token management requires authentication. Start the daemon with auth enabled (")}<code>SNDR_AUTH=on</code>{tr(") and sign in to mint revocable Bearer tokens.")}</p>;
  }
  return (
    <div className="token-manager">
      {created && (
        <div className="token-created">
          <div className="token-created-head"><KeyRound size={14} /> {tr("New token — copy it now, it won't be shown again")}</div>
          <div className="token-created-value"><code>{created}</code><CopyButton value={created} label={tr("API token")} /></div>
          <button className="ghost-button" onClick={() => setCreated(null)}>{tr("Dismiss")}</button>
        </div>
      )}
      <div className="token-create-row">
        <input aria-label={tr("New token label")} value={label} onChange={(event) => setLabel(event.target.value)} placeholder={tr("Token label (e.g. ci-readonly)")} maxLength={64} />
        <button className="primary-action" onClick={() => void create()} disabled={busy}><KeyRound size={15} /> {busy ? tr("Creating…") : tr("Create token")}</button>
      </div>
      {tokens && tokens.length > 0 ? (
        <table className="module-table token-table">
          <thead><tr><th>{tr("Label")}</th><th>{tr("Prefix")}</th><th>{tr("Created")}</th><th>{tr("Last used")}</th><th></th></tr></thead>
          <tbody>
            {tokens.map((token) => (
              <tr key={token.id}>
                <td><strong>{token.label}</strong></td>
                <td><code>{token.prefix}…</code></td>
                <td className="muted">{stamp(token.created_at)}</td>
                <td className="muted">{token.last_used ? stamp(token.last_used) : tr("never")}</td>
                <td><button className="icon-only danger" onClick={() => setConfirmRevoke({ id: token.id, label: token.label })} aria-label={`${tr("Revoke")} ${token.label}`}><Trash2 size={14} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted">{tr("No API tokens yet. Create one for programmatic / CI access — it authenticates as you via")} <code>Authorization: Bearer …</code>.</p>}
      {confirmRevoke && (
        <ConfirmDialog
          title={tr("Revoke API token?")}
          message={<>{tr("Revoking")} <strong>{confirmRevoke.label}</strong> {tr("immediately breaks any CI job or script that authenticates with it. This cannot be undone.")}</>}
          confirmLabel={tr("Revoke")}
          danger
          onConfirm={() => { const id = confirmRevoke.id; setConfirmRevoke(null); void revoke(id); }}
          onCancel={() => setConfirmRevoke(null)}
        />
      )}
    </div>
  );
}

export function ApiTokenField() {
  const [value, setValue] = useState(getApiToken());
  const [saved, setSaved] = useState(false);
  return (
    <div className="token-field">
      <label className="param-field">
        <span>{tr("Access token — for remote/tunnel daemons started with SNDR_GUI_TOKEN")}</span>
        <input
          type="password"
          value={value}
          onChange={(event) => { setValue(event.target.value); setSaved(false); }}
          placeholder={tr("leave empty for localhost (no auth)")}
        />
      </label>
      <div className="config-actions">
        <span className="config-actions-note">{saved ? tr("Saved — sent as Authorization: Bearer") : tr("Stored in this browser only")}</span>
        <button className="ghost-button" onClick={() => { setApiToken(""); setValue(""); setSaved(true); }}>{tr("Clear")}</button>
        <button className="primary-action" onClick={() => { setApiToken(value); setSaved(true); }}>
          <KeyRound size={14} /> {tr("Save token")}
        </button>
      </div>
    </div>
  );
}

// Telegram alerts / notifications settings — the global home for the engine
// health-watch config (also reachable from the Containers panel's bell button).
export function NotificationSettings() {
  const [cfg, setCfg] = useState<AlertConfig | null>(null);
  const [chatId, setChatId] = useState("");
  const [token, setToken] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  function reload() {
    api.alertsConfig().then((c) => { setCfg(c); setChatId(c.chat_id); }).catch((e) => setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) }));
  }
  useEffect(reload, []);

  async function save(enabled?: boolean) {
    setBusy(true); setMsg(null);
    try {
      const next = await api.alertsSetConfig({ enabled: enabled ?? cfg?.enabled, chat_id: chatId, ...(token ? { bot_token: token } : {}) });
      setCfg(next); setToken(""); setMsg({ ok: true, text: tr("Saved.") });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(false); }
  }
  async function test() {
    setBusy(true); setMsg(null);
    try { const r = await api.alertsTest(); setMsg({ ok: r.ok, text: r.ok ? tr("Test sent — check Telegram.") : (r.error || tr("Send failed")) }); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(false); }
  }

  if (!cfg) return <SkeletonLines count={4} />;
  return (
    <div className="notif">
      <div className="notif-grid">
        <div className="notif-fields">
          <div className="notif-row"><span>{tr("Enabled")}</span>
            <button className={`toggle ${cfg.enabled ? "on" : ""}`} disabled={busy} onClick={() => void save(!cfg.enabled)} aria-pressed={cfg.enabled} aria-label={tr("Enable alerts")}><span className="toggle-knob" /></button>
          </div>
          <label className="notif-row"><span>{tr("Telegram chat ID")}</span>
            <input value={chatId} onChange={(e) => setChatId(e.target.value)} placeholder={tr("e.g. 123456789")} />
          </label>
          <label className="notif-row"><span>{tr("Bot token")}</span>
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder={cfg.has_token ? tr("•••••• (stored — leave blank to keep)") : "123456:ABC-DEF…"} />
          </label>
          <div className="notif-status">
            <span className={`sev ${cfg.has_token ? "clean" : "low"}`}>{cfg.has_token ? tr("token stored") : tr("no token")}</span>
            <span className={`sev ${cfg.configured ? "clean" : "low"}`}>{cfg.configured ? tr("configured") : tr("incomplete")}</span>
            <span className={`sev ${cfg.enabled ? "clean" : "low"}`}>{cfg.enabled ? tr("watching") : tr("off")}</span>
          </div>
          <div className="notif-actions">
            <button className="primary-button" disabled={busy} onClick={() => void save()}>{busy ? <Loader2 size={13} className="spin" /> : <Settings size={13} />} {tr("Save")}</button>
            <button className="ghost-button" disabled={busy || !cfg.configured} onClick={() => void test()}><Send size={13} /> {tr("Send test")}</button>
          </div>
          {msg && <div className={msg.ok ? "notif-ok" : "notif-err"}>{!msg.ok && <AlertTriangle size={13} />} {msg.text}</div>}
        </div>
        <div className="notif-help">
          <h4><Bell size={14} /> {tr("What fires")}</h4>
          <ul>
            <li><b>🔴 {tr("DOWN")}</b> — {tr("a managed engine container exits / OOM-kills / is stopped.")}</li>
            <li><b>🟢 {tr("Recovered")}</b> — {tr("it comes back to running.")}</li>
          </ul>
          <h4>{tr("Set up Telegram")}</h4>
          <ol>
            <li>{tr("Message")} <code>@BotFather</code> → <code>/newbot</code> → {tr("copy the")} <b>{tr("bot token")}</b>.</li>
            <li>{tr("Message your new bot once, then open")} <code>api.telegram.org/bot&lt;token&gt;/getUpdates</code> {tr("and copy your")} <b>{tr("chat ID")}</b>.</li>
            <li>{tr("Paste both above, enable, and")} <b>{tr("Send test")}</b>.</li>
          </ol>
          <p className="notif-note">{tr("Token is stored encrypted. Env")} <code>SNDR_TELEGRAM_BOT_TOKEN</code> / <code>SNDR_TELEGRAM_CHAT_ID</code> / <code>SNDR_ALERTS=1</code> {tr("also work for headless deploys. Saving requires the daemon to run with")} <code>SNDR_ENABLE_APPLY=1</code>.</p>
        </div>
      </div>
    </div>
  );
}

export function AppearanceSettings({
  settings,
  onSettings
}: {
  settings: GuiSettings;
  onSettings: (patch: Partial<GuiSettings>) => void;
}) {
  return (
    <div className="settings-grid">
      <SettingGroup title={tr("Theme")} icon={<Palette size={16} />}>
        <SegmentedSetting
          value={settings.theme}
          options={[
            ["light", tr("Light")],
            ["dark", tr("Dark")],
            ["carbon", tr("Carbon")],
            ["lime", tr("Lime")]
          ]}
          onChange={(theme) => onSettings({ theme: theme as ThemeMode })}
        />
      </SettingGroup>
      <SettingGroup title={tr("Density")} icon={<Rows3 size={16} />}>
        <SegmentedSetting
          value={settings.density}
          options={[
            ["comfortable", tr("Comfortable")],
            ["compact", tr("Compact")]
          ]}
          onChange={(density) => onSettings({ density: density as DensityMode })}
        />
      </SettingGroup>
      <SettingGroup title={tr("Accent")} icon={<Sparkles size={16} />}>
        <SwatchSetting
          value={settings.accent}
          options={["teal", "blue", "emerald", "amber"]}
          onChange={(accent) => onSettings({ accent: accent as AccentMode })}
        />
      </SettingGroup>
      <SettingGroup title={tr("Detail Mode")} icon={<PanelLeft size={16} />}>
        <SegmentedSetting
          value={settings.detailMode}
          options={[
            ["operator", tr("Operator")],
            ["engineer", tr("Engineer")]
          ]}
          onChange={(detailMode) => onSettings({ detailMode: detailMode as DetailMode })}
        />
      </SettingGroup>
      <SettingGroup title={tr("Visual Layers")} icon={<Route size={16} />}>
        <ToggleSetting
          label={tr("Connection map")}
          active={settings.showConnectionMap}
          onClick={() => onSettings({ showConnectionMap: !settings.showConnectionMap })}
        />
        <ToggleSetting
          label={tr("Auto refresh")}
          active={settings.autoRefresh}
          onClick={() => onSettings({ autoRefresh: !settings.autoRefresh })}
        />
      </SettingGroup>
    </div>
  );
}

function SettingGroup({
  title,
  icon,
  children
}: {
  title: string;
  icon: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="setting-group">
      <h3>
        {icon}
        {title}
      </h3>
      {children}
    </section>
  );
}

function SegmentedSetting({
  value,
  options,
  onChange
}: {
  value: string;
  options: Array<[string, string]>;
  onChange: (value: string) => void;
}) {
  return (
    <div className="settings-segmented">
      {options.map(([id, label]) => (
        <button className={value === id ? "active" : ""} key={id} onClick={() => onChange(id)}>
          {label}
        </button>
      ))}
    </div>
  );
}

function SwatchSetting({
  value,
  options,
  onChange
}: {
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="swatch-row">
      {options.map((option) => (
        <button
          aria-label={`Use ${option} accent`}
          className={`swatch ${option} ${value === option ? "active" : ""}`}
          key={option}
          onClick={() => onChange(option)}
        />
      ))}
    </div>
  );
}

function ToggleSetting({
  label,
  active,
  onClick
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button className="settings-toggle" onClick={onClick}>
      <span>{label}</span>
      <i className={active ? "active" : ""} />
    </button>
  );
}

