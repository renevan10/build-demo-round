import { useEffect, useState } from "react";
import { getEmployees, getOffices, type Employee, type Office } from "./api";
import AllMeetingsPage from "./components/AllMeetingsPage";
import EmployeeSchedulePage from "./components/EmployeeSchedulePage";
import ScheduleMeetingForm from "./components/ScheduleMeetingForm";

type Tab = "schedule" | "all" | "employee";

const TABS: { id: Tab; label: string }[] = [
  { id: "schedule", label: "Schedule a meeting" },
  { id: "all", label: "All meetings" },
  { id: "employee", label: "Employee schedule" },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("schedule");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [offices, setOffices] = useState<Office[]>([]);
  const [directoryError, setDirectoryError] = useState<string | null>(null);
  const [loadingDirectory, setLoadingDirectory] = useState(true);
  // Bumped after every successful meeting creation so the list/schedule
  // tabs refetch even while they're not the active tab's first mount.
  const [refreshSignal, setRefreshSignal] = useState(0);

  useEffect(() => {
    Promise.all([getEmployees(), getOffices()])
      .then(([fetchedEmployees, fetchedOffices]) => {
        setEmployees(fetchedEmployees);
        setOffices(fetchedOffices);
      })
      .catch(() => setDirectoryError("backend-unreachable"))
      .finally(() => setLoadingDirectory(false));
  }, []);

  return (
    <div style={{ minHeight: "100vh" }}>
      <header
        style={{
          padding: "1.25rem 1.5rem",
          borderBottom: "1px solid var(--border)",
          background: "white",
        }}
      >
        <h1 style={{ margin: 0, fontSize: "1.25rem" }}>Meeting Scheduler</h1>
      </header>

      <nav
        style={{
          display: "flex",
          gap: "0.5rem",
          padding: "0.75rem 1.5rem",
          borderBottom: "1px solid var(--border)",
          background: "white",
        }}
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: "0.4rem 0.8rem",
              borderRadius: 6,
              border: "1px solid var(--border)",
              background: tab === t.id ? "var(--accent)" : "white",
              color: tab === t.id ? "white" : "inherit",
            }}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main style={{ padding: "1.5rem" }}>
        {loadingDirectory && <p>Loading…</p>}

        {directoryError && (
          <p style={{ color: "var(--danger)" }}>
            Can't reach the backend. Start it with{" "}
            <code>uvicorn app.main:app --reload</code>, then reload this page.
          </p>
        )}

        {!loadingDirectory && !directoryError && (
          <div
            style={{
              background: "white",
              border: "1px solid var(--border)",
              borderRadius: 8,
              padding: "1.25rem 1.5rem",
            }}
          >
            {tab === "schedule" && (
              <ScheduleMeetingForm
                employees={employees}
                offices={offices}
                onCreated={() => setRefreshSignal((n) => n + 1)}
              />
            )}
            {tab === "all" && <AllMeetingsPage refreshSignal={refreshSignal} />}
            {tab === "employee" && (
              <EmployeeSchedulePage employees={employees} refreshSignal={refreshSignal} />
            )}
          </div>
        )}
      </main>
    </div>
  );
}
