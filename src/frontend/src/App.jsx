import { useEffect, useState } from "react";

function App() {
  const [health, setHealth] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const load = async () => {
      try {
        const [healthRes, eventsRes] = await Promise.all([
          fetch("/api/health"),
          fetch("/api/events?limit=20")
        ]);

        const [healthData, eventsData] = await Promise.all([
          healthRes.json(),
          eventsRes.json()
        ]);

        setHealth(healthData);
        setEvents(eventsData);
      } catch (err) {
        console.error("Failed to load dashboard", err);
      } finally {
        setLoading(false);
      }
    };

    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <main className="mx-auto max-w-4xl px-4 pb-12 pt-8">
      <header className="mb-6">
        <h1 className="m-0 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">Manubot Control Panel</h1>
        <p className="mt-2 text-slate-500">v0.0.1</p>
      </header>

      <section className="mb-4 rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
        <h2 className="mt-0 text-xl font-semibold text-slate-900">Bot Health</h2>
        {loading && <p>Loading...</p>}
        {!loading && health && (
          <ul className="m-0 list-disc space-y-1 pl-5 text-slate-700">
            <li><span className="font-medium">Status:</span> {health.status}</li>
            <li><span className="font-medium">Connected:</span> {String(health.bot_connected)}</li>
            <li><span className="font-medium">Last Sequence:</span> {String(health.last_sequence)}</li>
            <li className="leading-7">
              Application ID:{" "}
              <span
                className="group ml-1 inline-block min-w-24 cursor-help rounded-md bg-slate-200 px-2 py-[1px] text-slate-500"
                title="Hover to reveal application ID"
              >
                <span className="group-hover:hidden">Show</span>
                <span className="hidden font-mono text-slate-800 group-hover:inline">{health.app_id || "not set"}</span>
              </span>
            </li>
          </ul>
        )}
      </section>

      <section className="mb-4 rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
        <h2 className="mt-0 text-xl font-semibold text-slate-900">Recent Gateway Events</h2>
        <div className="grid gap-3">
          {events.map((event) => (
            <article
              key={event.id}
              className="rounded-xl border border-slate-200 border-l-4 border-l-emerald-600 bg-slate-50 px-3 py-2"
            >
              <div className="flex justify-between">
                <strong>{event.event_type}</strong>
                <span>#{event.sequence ?? "-"}</span>
              </div>
              <small className="text-slate-500">{event.created_at}</small>
            </article>
          ))}
          {!events.length && !loading && <p>No events captured yet.</p>}
        </div>
      </section>
      <footer className="pt-2 text-center text-sm text-slate-500">
        <p className="m-0">© {new Date().getFullYear()} leafstudiosDot</p>
      </footer>
    </main>
  );
}

export default App;
