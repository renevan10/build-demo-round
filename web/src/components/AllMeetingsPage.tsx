import { useCallback, useEffect, useState } from "react";
import { getMeetings, type MeetingSummary } from "../api";
import MeetingTable from "./MeetingTable";
import Pager from "./Pager";

const LIMIT = 20;

export default function AllMeetingsPage({ refreshSignal }: { refreshSignal: number }) {
  const [meetings, setMeetings] = useState<MeetingSummary[]>([]);
  const [offset, setOffset] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getMeetings(LIMIT, offset)
      .then(setMeetings)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [offset]);

  useEffect(() => {
    load();
    // refreshSignal ticks whenever a meeting is created elsewhere in the app
  }, [load, refreshSignal]);

  return (
    <section>
      <h2 style={{ marginTop: 0 }}>All meetings</h2>
      {error && <p style={{ color: "var(--danger)" }}>{error}</p>}
      {loading ? <p>Loading…</p> : <MeetingTable meetings={meetings} />}
      <Pager
        offset={offset}
        limit={LIMIT}
        count={meetings.length}
        onPrev={() => setOffset((o) => Math.max(0, o - LIMIT))}
        onNext={() => setOffset((o) => o + LIMIT)}
      />
    </section>
  );
}
