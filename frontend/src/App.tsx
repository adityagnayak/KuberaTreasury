import { FormEvent, useMemo, useState } from "react";

type MetricCardProps = {
  title: string;
  value: string;
  note?: string;
  tone?: "default" | "alert" | "warn";
};

function MetricCard({ title, value, note, tone = "default" }: MetricCardProps) {
  return (
    <div className={`card ${tone}`}>
      <p className="label">{title}</p>
      <p className="value">{value}</p>
      {note ? <p className="note">{note}</p> : null}
    </div>
  );
}

type LoginFormState = {
  tenantId: string;
  email: string;
  password: string;
  totpCode: string;
  backupCode: string;
};

type AuthState = {
  accessToken: string;
  expiresIn: number;
};

function Dashboard({ email, onSignOut }: { email: string; onSignOut: () => void }) {
  return (
    <main className="shell">
      <header className="header topbar">
        <div>
          <h1>CFO 07:00 View</h1>
          <p>One screen. Three answers.</p>
        </div>
        <div className="topbar-actions">
          <span className="note">Signed in as {email}</span>
          <button className="btn btn-secondary" onClick={onSignOut}>
            Sign out
          </button>
        </div>
      </header>

      <section className="section">
        <h2>1) Do I have enough cash today?</h2>
        <MetricCard title="Group consolidated position" value="£12.4M" note="Available £8.1M · Committed £3.6M · In-transit £0.7M" />
        <div className="grid2">
          <MetricCard title="Today's payment queue" value="£1.2M" note="18 payments" />
          <MetricCard title="HMRC due in &lt; 7 days" value="£0.9M" note="VAT due in 5 days" tone="alert" />
        </div>
        <div className="chart">Entity breakdown (bar): UK HoldCo £6.2M · UK OpCo £4.1M · EU OpCo £2.1M</div>
      </section>

      <section className="section">
        <h2>2) Where is it?</h2>
        <div className="grid2">
          <div className="chart">Bank position (donut): Barclays 44% · HSBC 31% · NatWest 25%</div>
          <MetricCard title="Concentration alert" value="44%" note="Single bank concentration above 40%" tone="warn" />
        </div>
        <table className="table">
          <thead>
            <tr>
              <th>Currency</th>
              <th>Balance</th>
              <th>GBP equivalent</th>
            </tr>
          </thead>
          <tbody>
            <tr><td>GBP</td><td>£7.9M</td><td>£7.9M</td></tr>
            <tr><td>USD</td><td>$3.1M</td><td>£2.4M</td></tr>
            <tr><td>EUR</td><td>€2.5M</td><td>£2.1M</td></tr>
          </tbody>
        </table>
      </section>

      <section className="section">
        <h2>3) What will it look like in 90 days?</h2>
        <div className="chart">Waterfall: Today £12.4M → HMRC (red) → Committed (amber) → Forecast band (blue) → 90-day closing £9.8M</div>
        <div className="grid2">
          <div className="card">
            <p className="label">Next 5 HMRC obligations</p>
            <p className="note">05 Mar VAT £0.9M · 19 Mar PAYE £0.4M · 01 Apr CT £1.1M · 19 Apr PAYE £0.4M · 07 May VAT £0.8M</p>
          </div>
          <div className="card">
            <p className="label">Covenant headroom</p>
            <p className="value">28%</p>
            <p className="note">Minimum balance covenant line intact</p>
          </div>
        </div>
        <MetricCard title="CIR status" value="Amber" note="£1.85M projected vs £2.0M threshold" tone="warn" />
      </section>
    </main>
  );
}

const AUTH_STORAGE_KEY = "kuberaSandboxAuth";

export function App() {
  const apiBaseUrl = useMemo(
    () => import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000",
    []
  );

  const [form, setForm] = useState<LoginFormState>({
    tenantId: "",
    email: "",
    password: "",
    totpCode: "",
    backupCode: "",
  });
  const [auth, setAuth] = useState<AuthState | null>(() => {
    const saved = localStorage.getItem(AUTH_STORAGE_KEY);
    if (!saved) return null;
    try {
      return JSON.parse(saved) as AuthState;
    } catch {
      return null;
    }
  });
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const handleInput = (key: keyof LoginFormState, value: string) => {
    setForm((prev) => ({ ...prev, [key]: value }));
  };

  const submitLogin = async (event: FormEvent) => {
    event.preventDefault();
    setErrorMessage(null);
    setIsSubmitting(true);

    try {
      const payload: Record<string, string> = {
        tenant_id: form.tenantId.trim(),
        email: form.email.trim(),
        password: form.password,
      };
      if (form.totpCode.trim()) payload.totp_code = form.totpCode.trim();
      if (form.backupCode.trim()) payload.backup_code = form.backupCode.trim();

      const response = await fetch(`${apiBaseUrl}/api/v1/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const details = (await response.json().catch(() => ({}))) as {
          detail?: string;
        };
        throw new Error(details.detail ?? "Login failed");
      }

      const token = (await response.json()) as {
        access_token: string;
        expires_in: number;
      };
      const nextAuth: AuthState = {
        accessToken: token.access_token,
        expiresIn: token.expires_in,
      };
      setAuth(nextAuth);
      localStorage.setItem(AUTH_STORAGE_KEY, JSON.stringify(nextAuth));
    } catch (error) {
      if (error instanceof TypeError && error.message === "Failed to fetch") {
        setErrorMessage(
          "Cannot reach API. Confirm backend is running and CORS allows your frontend origin (localhost/127.0.0.1)."
        );
      } else {
        setErrorMessage(error instanceof Error ? error.message : "Login failed");
      }
    } finally {
      setIsSubmitting(false);
    }
  };

  const signOut = () => {
    setAuth(null);
    localStorage.removeItem(AUTH_STORAGE_KEY);
  };

  if (auth) {
    return <Dashboard email={form.email || "user"} onSignOut={signOut} />;
  }

  return (
    <main className="shell auth-shell">
      <section className="section auth-card">
        <h1>Client Sandbox Login</h1>
        <p className="note">Connects to your live local backend auth API.</p>

        <form className="auth-form" onSubmit={submitLogin}>
          <label className="field">
            <span>Tenant ID</span>
            <input
              value={form.tenantId}
              onChange={(e) => handleInput("tenantId", e.target.value)}
              placeholder="UUID from tenant onboarding"
              required
            />
          </label>

          <label className="field">
            <span>Email</span>
            <input
              type="email"
              value={form.email}
              onChange={(e) => handleInput("email", e.target.value)}
              placeholder="admin@client.com"
              required
            />
          </label>

          <label className="field">
            <span>Password</span>
            <input
              type="password"
              value={form.password}
              onChange={(e) => handleInput("password", e.target.value)}
              required
            />
          </label>

          <div className="grid2">
            <label className="field">
              <span>TOTP code (optional)</span>
              <input
                value={form.totpCode}
                onChange={(e) => handleInput("totpCode", e.target.value)}
                placeholder="123456"
              />
            </label>

            <label className="field">
              <span>Backup code (optional)</span>
              <input
                value={form.backupCode}
                onChange={(e) => handleInput("backupCode", e.target.value)}
                placeholder="Backup code"
              />
            </label>
          </div>

          {errorMessage ? <p className="error">{errorMessage}</p> : null}

          <button className="btn" type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Signing in..." : "Sign in"}
          </button>
        </form>

        <p className="note api-hint">API: {apiBaseUrl}/api/v1/auth/login</p>
      </section>
    </main>
  );
}
