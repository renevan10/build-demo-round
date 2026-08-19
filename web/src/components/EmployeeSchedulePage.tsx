import { useCallback, useEffect, useState } from "react";
import { getEmployeeSchedule, submitMeetingFeedback, type Employee, type MeetingSummary } from "../api";
import MeetingTable from "./MeetingTable";
import Pager from "./Pager";

const LIMIT = 20;

export default function EmployeeSchedulePage({
  employees,
  refreshSignal,
}: {
  employees: Employee[];
  refreshSignal: number;
}) {
  const [employeeId, setEmployeeId] = useState<number | null>(null);
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (employeeId === null && employees.length > 0) {
      setEmployeeId(employees[0].id);
    }
  }, [employees, employeeId]);

  const load = useCallback(() => {
    if (employeeId === null) return;
    setLoading(true);
    setError(null);
    getEmployeeSchedule(employeeId, LIMIT, offset)
      .then(setMeetings)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [employeeId, offset]);

  useEffect(() => {
    load();
  }, [load, refreshSignal]);

  async function handleRate(meetingId: number, score: number) {
    if (employeeId === null) return;
    await submitMeetingFeedback(meetingId, employeeId, score);
    load(); // refetch so the new my_usefulness_score flows back down
  }

  return (
    <section>
      <h2 style={{ marginTop: 0 }}>Employee schedule</h2>
      <label>
        Employee:{" "}
        <select
          value={employeeId ?? ""}
          onChange={(e) => {
            setOffset(0);
            setEmployeeId(Number(e.target.value));
          }}
        >
          {employees.map((employee) => (
            <option key={employee.id} value={employee.id}>
              {employee.name} — {employee.timezone}
            </option>
          ))}
        </select>
      </label>
      <div style={{ marginTop: "1rem" }}>
        {error && <p style={{ color: "var(--danger)" }}>{error}</p>}
        {loading ? (
          <p>Loading…</p>
        ) : (
          <MeetingTable
            meetings={meetings}
            viewerEmployeeId={employeeId ?? undefined}
            onRate={handleRate}
          />
        )}
        <Pager
          offset={offset}
          limit={LIMIT}
          count={meetings.length}
          onPrev={() => setOffset((o) => Math.max(0, o - LIMIT))}
          onNext={() => setOffset((o) => o + LIMIT)}
        />
      </div>
    </section>
  );
}
