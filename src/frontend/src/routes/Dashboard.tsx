function Dashboard({ loading, health, events }) {
  return (
    <>
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
    </>
  );
}

export default Dashboard;
