import { useCallback, useEffect, useState } from "react";
import { getMeetingTimeDashboard, type EmployeeMeetingTime } from "../api";

// Wide enough to cover the seeded adversarial dataset (Jan-Aug 2026) out
// of the box; the range is a plain filter, not tied to "today" in any
// particular timezone -- there's no single "today" that's correct for
// every employee at once.
const DEFAULT_START = "2026-01-01";
const DEFAULT_END = "2026-12-31";

export default function DashboardPage({ refreshSignal }: { refreshSignal: number }) {
  const [startDate, setStartDate] = useState(DEFAULT_START);
  const [endDate, setEndDate] = useState(DEFAULT_END);
  const [data, setData] = useState<EmployeeMeetingTime[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const rangeIsValid = startDate !== "" && endDate !== "" && endDate >= startDate;

  const load = useCallback(() => {
    // A user filling in "From" and "To" one field at a time can pass
    // through an invalid range for a moment (native date inputs can fire
    // onChange per field). Skip the fetch rather than flash an error for
    // a transient state -- the chart just holds its last valid render
    // until both fields agree again, per "refetch keeps the frame."
    if (!rangeIsValid) return;
    setLoading(true);
    setError(null);
    getMeetingTimeDashboard(startDate, endDate)
      .then(setData)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [startDate, endDate, rangeIsValid]);

  useEffect(() => {
    load();
  }, [load, refreshSignal]);

  const maxHours = Math.max(1, ...data.map((d) => d.total_hours));

  return (
    <section>
      <h2 style={{ marginTop: 0 }}>Meeting time per employee</h2>
      <p style={{ color: "var(--muted)", marginTop: "-0.5rem", maxWidth: 640 }}>
        Total hours in the selected range, plus daily/weekly/monthly averages. Each
        meeting counts toward the employee's own local calendar day -- two people on
        the same call can land it on different days if they're far enough apart in
        timezone.
      </p>

      <div style={{ display: "flex", gap: "1rem", alignItems: "flex-end", margin: "1rem 0 1.5rem" }}>
        <label style={fieldStyle}>
          From
          <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
        </label>
        <label style={fieldStyle}>
          To
          <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
        </label>
      </div>

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      {loading ? (
        <p>Loading…</p>
      ) : data.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>No employees.</p>
      ) : (
        <>
          <MeetingHoursBarChart data={data} maxHours={maxHours} />
          <MeetingTimeTable data={data} />
        </>
      )}
    </section>
  );
}

function MeetingHoursBarChart({ data, maxHours }: { data: EmployeeMeetingTime[]; maxHours: number }) {
  return (
    <div
      role="img"
      aria-label="Total meeting hours per employee in the selected range"
      style={{ display: "grid", gap: "0.4rem", marginBottom: "1.75rem" }}
    >
      {data.map((d) => (
        <div key={d.employee_id} className="bar-row" tabIndex={0}>
          <span className="bar-row-label">{d.employee_name}</span>
          <div className="bar-row-track">
            <div
              className="bar-row-fill"
              style={{ width: `${Math.max(2, (d.total_hours / maxHours) * 100)}%` }}
            />
            <span className="bar-row-value">{d.total_hours}h</span>
          </div>
          <div className="bar-tooltip">
            {d.meeting_count} meeting{d.meeting_count === 1 ? "" : "s"} · avg{" "}
            {d.avg_hours_per_week}h/week · {d.avg_hours_per_month}h/month
          </div>
        </div>
      ))}
    </div>
  );
}

function MeetingTimeTable({ data }: { data: EmployeeMeetingTime[] }) {
  return (
    <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
      <thead>
        <tr>
          <th style={headerCellStyle}>Employee</th>
          <th style={headerCellStyle}>Meetings</th>
          <th style={headerCellStyle}>Total hours</th>
          <th style={headerCellStyle}>Avg / day</th>
          <th style={headerCellStyle}>Avg / week</th>
          <th style={headerCellStyle}>Avg / month</th>
        </tr>
      </thead>
      <tbody>
        {data.map((d) => (
          <tr key={d.employee_id} style={{ borderBottom: "1px solid #f0f0f0" }}>
            <td style={cellStyle}>{d.employee_name}</td>
            <td style={cellStyle}>{d.meeting_count}</td>
            <td style={cellStyle}>{d.total_hours}</td>
            <td style={cellStyle}>{d.avg_hours_per_day}</td>
            <td style={cellStyle}>{d.avg_hours_per_week}</td>
            <td style={cellStyle}>{d.avg_hours_per_month}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

const fieldStyle = { display: "flex", flexDirection: "column" as const, gap: "0.3rem" };
const cellStyle = { padding: "0.5rem 0.75rem" };
const headerCellStyle = { ...cellStyle, textAlign: "left" as const, borderBottom: "2px solid #e5e7eb" };
