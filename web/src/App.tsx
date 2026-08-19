import { useEffect, useState } from "react";
import { getHealth } from "./api";

type BackendStatus = "checking" | "ok" | "unreachable";

export default function App() {
  const [status, setStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    getHealth()
      .then(() => setStatus("ok"))
      .catch(() => setStatus("unreachable"));
  }, []);

  return (
    <main style={{ fontFamily: "system-ui, sans-serif", padding: "2rem" }}>
      <h1>Build &amp; Demo round</h1>
      <p>
        Backend (<code>uvicorn app.main:app</code> on :8000): <strong>{status}</strong>
      </p>
      {status === "unreachable" && (
        <p>Start the API first: <code>uvicorn app.main:app --reload</code></p>
      )}
    </main>
  );
}
