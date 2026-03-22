function Dashboard({ loading, health, events }) {
  const profile = health?.bot_profile;

  return (
    <>
      {profile && (
        <section className="mb-4 overflow-hidden rounded-2xl bg-white shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
          <div className="w-full bg-gradient-to-r from-sky-600 via-blue-600 to-indigo-700 select-none">
            {profile.banner_url ? (
              <img src={profile.banner_url} alt="Profile Header" className="block h-auto w-full" draggable={false} />
            ) : (
              <div className="aspect-[16/5] w-full" />
            )}
          </div>

          <div className="px-5 pb-5">
            <div className="-mt-10 select-none">
              <div className="h-20 w-20 overflow-hidden rounded-full border-4 border-white bg-slate-200 shadow-sm">
                {profile.avatar_url ? (
                  <img src={profile.avatar_url} alt="Profile Avatar" className="h-full w-full object-cover" draggable={false} />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-lg font-bold text-slate-500">
                    {String(profile.username || "M").charAt(0).toUpperCase()}
                  </div>
                )}
              </div>

              <div className="pt-3 flex">
                <h2 className="m-0 text-2xl font-semibold text-slate-900">{profile.username}</h2>
                <p className="m-0 text-slate-500 font-[23px]">#{profile.discriminator || "0000"}</p>
              </div>
            </div>
          </div>
        </section>
      )}

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
