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

export function App() {
  return (
    <main className="shell">
      <header className="header">
        <h1>CFO 07:00 View</h1>
        <p>One screen. Three answers.</p>
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
