export default function Pager({
  offset,
  limit,
  count,
  onPrev,
  onNext,
}: {
  offset: number;
  limit: number;
  count: number;
  onPrev: () => void;
  onNext: () => void;
}) {
  return (
    <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", marginTop: "0.75rem" }}>
      <button onClick={onPrev} disabled={offset === 0}>
        Previous
      </button>
      <span style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
        Showing {count === 0 ? 0 : offset + 1}–{offset + count}
      </span>
      <button onClick={onNext} disabled={count < limit}>
        Next
      </button>
    </div>
  );
}
