import { useCallback, useEffect, useState } from "react";
import { getMeetingTimeDashboard, type EmployeeMeetingTime } from "../api";

export default function MeetingTimeSection({
  startDate,
  endDate,
  rangeIsValid,
  refreshSignal,
}: {
  startDate: string;
  endDate: string;
  rangeIsValid: boolean;
  refreshSignal: number;
}) {
  const [data, setData] = useState<EmployeeMeetingTime[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
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
    <section style={{ marginBottom: "2.5rem" }}>
      <h2 style={{ marginTop: 0, marginBottom: "0.25rem" }}>Meeting time per employee</h2>
      <p style={{ color: "var(--muted)", marginTop: 0, maxWidth: 640 }}>
        Total hours in the selected range, plus daily/weekly/monthly averages. Each
        meeting counts toward the employee's own local calendar day -- two people on
        the same call can land it on different days if they're far enough apart in
        timezone.
      </p>

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

const cellStyle = { padding: "0.5rem 0.75rem" };
const headerCellStyle = { ...cellStyle, textAlign: "left" as const, borderBottom: "2px solid #e5e7eb" };
