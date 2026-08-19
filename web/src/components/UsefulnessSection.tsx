import { useCallback, useEffect, useState } from "react";
import {
  getUsefulnessDashboard,
  type LowRatedMeeting,
  type OrganizerUsefulness,
  type PriorityUsefulness,
  type UsefulnessSummary,
} from "../api";

const PRIORITY_LABELS: Record<string, string> = {
  low: "Low",
  medium: "Medium",
  high: "High",
  critical: "Critical",
};

const USEFULNESS_SCALE_MAX = 5;

export default function UsefulnessSection({
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
  const [data, setData] = useState<UsefulnessSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!rangeIsValid) return;
    setLoading(true);
    setError(null);
    getUsefulnessDashboard(startDate, endDate)
      .then(setData)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [startDate, endDate, rangeIsValid]);

  useEffect(() => {
    load();
  }, [load, refreshSignal]);

  return (
    <section>
      <h2 style={{ marginTop: 0, marginBottom: "0.25rem" }}>Usefulness</h2>
      <p style={{ color: "var(--muted)", marginTop: 0, maxWidth: 640 }}>
        How the meetings people actually rated afterward compare to how much priority
        they were given -- a critical meeting that scores low is exactly the "expensive
        but not useful" case worth reconsidering.
      </p>

      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}

      {loading && <p>Loading…</p>}

      {!loading && data && (
        <>
          <CoverageMeter rated={data.coverage_rated} eligible={data.coverage_eligible} />
          <PriorityBarChart rows={data.by_priority} />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "2rem", marginTop: "1.5rem" }}>
            <OrganizerTable rows={data.by_organizer} />
            <NeedsAttentionTable rows={data.needs_attention} />
          </div>
        </>
      )}
    </section>
  );
}

function CoverageMeter({ rated, eligible }: { rated: number; eligible: number }) {
  if (eligible === 0) {
    return (
      <p style={{ color: "var(--muted)", marginBottom: "1.5rem" }}>
        No completed meetings in this range yet.
      </p>
    );
  }
  const pct = Math.round((rated / eligible) * 100);
  return (
    <div style={{ marginBottom: "1.75rem", maxWidth: 420 }}>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.85rem", marginBottom: "0.3rem" }}>
        <span>Feedback coverage</span>
        <span style={{ color: "var(--muted)" }}>
          {rated} of {eligible} meetings rated ({pct}%)
        </span>
      </div>
      <div style={{ height: 10, borderRadius: 5, background: "#dbeafe", overflow: "hidden" }}>
        <div
          style={{
            height: "100%",
            width: `${Math.max(2, pct)}%`,
            background: "var(--accent)",
            borderRadius: 5,
          }}
        />
      </div>
    </div>
  );
}

function PriorityBarChart({ rows }: { rows: PriorityUsefulness[] }) {
  return (
    <div
      role="img"
      aria-label="Average usefulness score by meeting priority"
      style={{ display: "grid", gap: "0.4rem", marginBottom: "0.5rem" }}
    >
      {rows.map((row) => (
        <div key={row.priority} className="bar-row" tabIndex={0}>
          <span className="bar-row-label">{PRIORITY_LABELS[row.priority] ?? row.priority}</span>
          <div className="bar-row-track">
            {row.avg_score === null ? (
              <span style={{ color: "var(--muted)", fontSize: "0.8rem" }}>No ratings yet</span>
            ) : (
              <>
                <div
                  className="bar-row-fill"
                  style={{ width: `${Math.max(2, (row.avg_score / USEFULNESS_SCALE_MAX) * 100)}%` }}
                />
                <span className="bar-row-value">{row.avg_score.toFixed(1)}</span>
              </>
            )}
          </div>
          <div className="bar-tooltip">
            {row.rated_meeting_count} of {row.total_meeting_count} meeting
            {row.total_meeting_count === 1 ? "" : "s"} rated
          </div>
        </div>
      ))}
    </div>
  );
}

function OrganizerTable({ rows }: { rows: OrganizerUsefulness[] }) {
  return (
    <div>
      <h3 style={subheadingStyle}>By organizer</h3>
      {rows.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>No organizers in range.</p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr>
              <th style={headerCellStyle}>Organizer</th>
              <th style={headerCellStyle}>Avg score</th>
              <th style={headerCellStyle}>Rated</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.organizer_id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                <td style={cellStyle}>{row.organizer_name}</td>
                <td style={cellStyle}>{row.avg_score === null ? "—" : row.avg_score.toFixed(1)}</td>
                <td style={cellStyle}>
                  {row.rated_meeting_count} / {row.total_meeting_count}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

function NeedsAttentionTable({ rows }: { rows: LowRatedMeeting[] }) {
  return (
    <div>
      <h3 style={subheadingStyle}>Needs attention</h3>
      {rows.length === 0 ? (
        <p style={{ color: "var(--muted)" }}>
          Nothing high/critical priority has a low rating in this range.
        </p>
      ) : (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr>
              <th style={headerCellStyle}>Meeting</th>
              <th style={headerCellStyle}>Priority</th>
              <th style={headerCellStyle}>Avg score</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.meeting_id} style={{ borderBottom: "1px solid #f0f0f0" }}>
                <td style={cellStyle}>
                  {row.title}
                  <div style={{ color: "var(--muted)", fontSize: "0.78rem" }}>{row.organizer_name}</div>
                </td>
                <td style={cellStyle}>{PRIORITY_LABELS[row.priority] ?? row.priority}</td>
                <td style={cellStyle}>
                  {row.avg_score.toFixed(1)} ({row.feedback_count})
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

const cellStyle = { padding: "0.4rem 0.6rem" };
const headerCellStyle = { ...cellStyle, textAlign: "left" as const, borderBottom: "2px solid #e5e7eb" };
const subheadingStyle = { fontSize: "1rem", marginBottom: "0.5rem" };
