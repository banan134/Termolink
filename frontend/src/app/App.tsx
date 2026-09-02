import { useQuery } from "@tanstack/react-query";
import { Route, Routes } from "react-router-dom";
import styles from "./App.module.css";

type Health = { status: string; db: boolean };

async function fetchHealth(): Promise<Health> {
  const res = await fetch("/api/v1/health");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function Home() {
  const health = useQuery({ queryKey: ["health"], queryFn: fetchHealth, refetchInterval: 10_000 });

  let status: { text: string; tone: "ok" | "danger" | "neutral" };
  if (health.isPending) status = { text: "Sprawdzanie…", tone: "neutral" };
  else if (health.isError) status = { text: "API niedostępne", tone: "danger" };
  else
    status = health.data.db
      ? { text: "API: ok · baza: ok", tone: "ok" }
      : { text: "API: ok · baza: błąd", tone: "danger" };

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <span className={styles.logo}>Termolink</span>
      </header>
      <section className={styles.card}>
        <h1 className={styles.title}>Szkielet aplikacji działa</h1>
        <p className={styles.muted}>
          Etap 1 — fundament. Interfejs użytkownika pojawi się w kolejnych zadaniach z{" "}
          <code>docs/13-roadmap.md</code>.
        </p>
        <p>
          <span className={`${styles.chip} ${styles[status.tone]}`} role="status">
            {status.text}
          </span>
        </p>
        <ul className={styles.links}>
          <li>
            <a href="/api/schema/swagger/">OpenAPI (Swagger)</a>
          </li>
          <li>
            <a href="/admin-django/">Panel Django (dev)</a>
          </li>
          <li>
            <a href="http://localhost:8025">Mailpit</a>
          </li>
        </ul>
      </section>
    </main>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="*" element={<Home />} />
    </Routes>
  );
}
