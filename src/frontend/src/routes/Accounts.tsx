function Accounts() {
    return (<>
        <section className="mb-4 rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
            <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                    <h2 className="m-0 text-xl font-semibold text-slate-900">Accounts</h2>
                    <p className="mb-0 mt-1 text-sm text-slate-500">Accounts listed here have access to this control panel.</p>
                </div>
                <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700">
                    0 total
                </span>
            </div>
        </section>
    </>)
}

export default Accounts;