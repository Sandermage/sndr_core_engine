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
      toast("API token created", "success");
    } catch {
      toast("Failed to create token", "error");
    } finally { setBusy(false); }
  }
  async function revoke(id: string) {
    try { await api.apiTokenRevoke(id); load(); toast("Token revoked", "success"); } catch { toast("Failed to revoke token", "error"); }
  }
  const [confirmRevoke, setConfirmRevoke] = useState<{ id: string; label: string } | null>(null);
  const stamp = (ts: number) => new Date(ts * 1000).toLocaleDateString([], { month: "short", day: "2-digit", year: "numeric" });
  if (unavailable) {
    return <p className="muted">API token management requires authentication. Start the daemon with auth enabled (<code>SNDR_AUTH=on</code>) and sign in to mint revocable Bearer tokens.</p>;
  }
  return (
    <div className="token-manager">
      {created && (
        <div className="token-created">
          <div className="token-created-head"><KeyRound size={14} /> New token — copy it now, it won't be shown again</div>
          <div className="token-created-value"><code>{created}</code><CopyButton value={created} label="API token" /></div>
          <button className="ghost-button" onClick={() => setCreated(null)}>Dismiss</button>
        </div>
      )}
      <div className="token-create-row">
        <input aria-label="New token label" value={label} onChange={(event) => setLabel(event.target.value)} placeholder="Token label (e.g. ci-readonly)" maxLength={64} />
        <button className="primary-action" onClick={() => void create()} disabled={busy}><KeyRound size={15} /> {busy ? "Creating…" : "Create token"}</button>
      </div>
      {tokens && tokens.length > 0 ? (
        <table className="module-table token-table">
          <thead><tr><th>Label</th><th>Prefix</th><th>Created</th><th>Last used</th><th></th></tr></thead>
          <tbody>
            {tokens.map((token) => (
              <tr key={token.id}>
                <td><strong>{token.label}</strong></td>
                <td><code>{token.prefix}…</code></td>
                <td className="muted">{stamp(token.created_at)}</td>
                <td className="muted">{token.last_used ? stamp(token.last_used) : "never"}</td>
                <td><button className="icon-only danger" onClick={() => setConfirmRevoke({ id: token.id, label: token.label })} aria-label={`Revoke ${token.label}`}><Trash2 size={14} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : <p className="muted">No API tokens yet. Create one for programmatic / CI access — it authenticates as you via <code>Authorization: Bearer …</code>.</p>}
      {confirmRevoke && (
        <ConfirmDialog
          title="Revoke API token?"
          message={<>Revoking <strong>{confirmRevoke.label}</strong> immediately breaks any CI job or script that authenticates with it. This cannot be undone.</>}
          confirmLabel="Revoke"
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
        <span>Access token — for remote/tunnel daemons started with SNDR_GUI_TOKEN</span>
        <input
          type="password"
          value={value}
          onChange={(event) => { setValue(event.target.value); setSaved(false); }}
          placeholder="leave empty for localhost (no auth)"
        />
      </label>
      <div className="config-actions">
        <span className="config-actions-note">{saved ? "Saved — sent as Authorization: Bearer" : "Stored in this browser only"}</span>
        <button className="ghost-button" onClick={() => { setApiToken(""); setValue(""); setSaved(true); }}>Clear</button>
        <button className="primary-action" onClick={() => { setApiToken(value); setSaved(true); }}>
          <KeyRound size={14} /> Save token
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
      setCfg(next); setToken(""); setMsg({ ok: true, text: "Saved." });
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(false); }
  }
  async function test() {
    setBusy(true); setMsg(null);
    try { const r = await api.alertsTest(); setMsg({ ok: r.ok, text: r.ok ? "Test sent — check Telegram." : (r.error || "Send failed") }); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) }); }
    finally { setBusy(false); }
  }

  if (!cfg) return <SkeletonLines count={4} />;
  return (
    <div className="notif">
      <div className="notif-grid">
        <div className="notif-fields">
          <div className="notif-row"><span>Enabled</span>
            <button className={`toggle ${cfg.enabled ? "on" : ""}`} disabled={busy} onClick={() => void save(!cfg.enabled)} aria-pressed={cfg.enabled} aria-label="Enable alerts"><span className="toggle-knob" /></button>
          </div>
          <label className="notif-row"><span>Telegram chat ID</span>
            <input value={chatId} onChange={(e) => setChatId(e.target.value)} placeholder="e.g. 123456789" />
          </label>
          <label className="notif-row"><span>Bot token</span>
            <input type="password" value={token} onChange={(e) => setToken(e.target.value)} placeholder={cfg.has_token ? "•••••• (stored — leave blank to keep)" : "123456:ABC-DEF…"} />
          </label>
          <div className="notif-status">
            <span className={`sev ${cfg.has_token ? "clean" : "low"}`}>{cfg.has_token ? "token stored" : "no token"}</span>
            <span className={`sev ${cfg.configured ? "clean" : "low"}`}>{cfg.configured ? "configured" : "incomplete"}</span>
            <span className={`sev ${cfg.enabled ? "clean" : "low"}`}>{cfg.enabled ? "watching" : "off"}</span>
          </div>
          <div className="notif-actions">
            <button className="primary-button" disabled={busy} onClick={() => void save()}>{busy ? <Loader2 size={13} className="spin" /> : <Settings size={13} />} Save</button>
            <button className="ghost-button" disabled={busy || !cfg.configured} onClick={() => void test()}><Send size={13} /> Send test</button>
          </div>
          {msg && <div className={msg.ok ? "notif-ok" : "notif-err"}>{!msg.ok && <AlertTriangle size={13} />} {msg.text}</div>}
        </div>
        <div className="notif-help">
          <h4><Bell size={14} /> What fires</h4>
          <ul>
            <li><b>🔴 DOWN</b> — a managed engine container exits / OOM-kills / is stopped.</li>
            <li><b>🟢 Recovered</b> — it comes back to running.</li>
          </ul>
          <h4>Set up Telegram</h4>
          <ol>
            <li>Message <code>@BotFather</code> → <code>/newbot</code> → copy the <b>bot token</b>.</li>
            <li>Message your new bot once, then open <code>api.telegram.org/bot&lt;token&gt;/getUpdates</code> and copy your <b>chat ID</b>.</li>
            <li>Paste both above, enable, and <b>Send test</b>.</li>
          </ol>
          <p className="notif-note">Token is stored encrypted. Env <code>SNDR_TELEGRAM_BOT_TOKEN</code> / <code>SNDR_TELEGRAM_CHAT_ID</code> / <code>SNDR_ALERTS=1</code> also work for headless deploys. Saving requires the daemon to run with <code>SNDR_ENABLE_APPLY=1</code>.</p>
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
      <SettingGroup title="Theme" icon={<Palette size={16} />}>
        <SegmentedSetting
          value={settings.theme}
          options={[
            ["light", "Light"],
            ["dark", "Dark"],
            ["carbon", "Carbon"],
            ["lime", "Lime"]
          ]}
          onChange={(theme) => onSettings({ theme: theme as ThemeMode })}
        />
      </SettingGroup>
      <SettingGroup title="Density" icon={<Rows3 size={16} />}>
        <SegmentedSetting
          value={settings.density}
          options={[
            ["comfortable", "Comfortable"],
            ["compact", "Compact"]
          ]}
          onChange={(density) => onSettings({ density: density as DensityMode })}
        />
      </SettingGroup>
      <SettingGroup title="Accent" icon={<Sparkles size={16} />}>
        <SwatchSetting
          value={settings.accent}
          options={["teal", "blue", "emerald", "amber"]}
          onChange={(accent) => onSettings({ accent: accent as AccentMode })}
        />
      </SettingGroup>
      <SettingGroup title="Detail Mode" icon={<PanelLeft size={16} />}>
        <SegmentedSetting
          value={settings.detailMode}
          options={[
            ["operator", "Operator"],
            ["engineer", "Engineer"]
          ]}
          onChange={(detailMode) => onSettings({ detailMode: detailMode as DetailMode })}
        />
      </SettingGroup>
      <SettingGroup title="Visual Layers" icon={<Route size={16} />}>
        <ToggleSetting
          label="Connection map"
          active={settings.showConnectionMap}
          onClick={() => onSettings({ showConnectionMap: !settings.showConnectionMap })}
        />
        <ToggleSetting
          label="Auto refresh"
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

