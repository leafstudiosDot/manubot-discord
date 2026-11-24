import { useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api";

type AuditEvent = {
    id: number;
    actor_account_id: number | null;
    actor_username: string;
    actor_role: string;
    action: string;
    category: string;
    target_type: string | null;
    target_id: string | null;
    metadata: Record<string, unknown>;
    created_at: string;
};

type AuditMeta = {
    categories: Array<{ value: string; label: string }>;
    actions: Array<{ value: string; label: string }>;
};

type AuditLogsProps = {
    canView: boolean;
};

const PAGE_SIZE = 25;

function formatTimestamp(value: string) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return value || "—";
    }
    return parsed.toLocaleString();
}

function formatValue(value: unknown) {
    if (value === null || value === undefined || value === "") {
        return "—";
    }
    if (typeof value === "string") {
        return value;
    }
    return JSON.stringify(value);
}

function AuditLogs({ canView }: AuditLogsProps) {
    const [events, setEvents] = useState<AuditEvent[]>([]);
    const [meta, setMeta] = useState<AuditMeta>({ categories: [], actions: [] });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [page, setPage] = useState(1);
    const [pages, setPages] = useState(1);
    const [total, setTotal] = useState(0);

    const [category, setCategory] = useState("");
    const [action, setAction] = useState("");
    const [actor, setActor] = useState("");
    const [targetType, setTargetType] = useState("");
    const [targetId, setTargetId] = useState("");
    const [query, setQuery] = useState("");
    const [fromDate, setFromDate] = useState("");
    const [toDate, setToDate] = useState("");

    const [selectedEvent, setSelectedEvent] = useState<AuditEvent | null>(null);
    const [detailError, setDetailError] = useState<string | null>(null);

    const actionLabels = useMemo(() => {
        const map: Record<string, string> = {};
        meta.actions.forEach((item) => {
            map[item.value] = item.label;
        });
        return map;
    }, [meta.actions]);

    const categoryLabels = useMemo(() => {
        const map: Record<string, string> = {};
        meta.categories.forEach((item) => {
            map[item.value] = item.label;
        });
        return map;
    }, [meta.categories]);

    useEffect(() => {
        if (!canView) {
            setLoading(false);
            return;
        }

        let cancelled = false;

        const loadMeta = async () => {
            try {
                const response = await apiFetch("/api/audit-logs/meta");
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    return;
                }
                if (!cancelled) {
                    setMeta({
                        categories: Array.isArray(data?.categories) ? data.categories : [],
                        actions: Array.isArray(data?.actions) ? data.actions : [],
                    });
                }
            } catch {
                // Filters fall back to free-text values when metadata fails.
            }
        };

        const params = new URLSearchParams({
            page: String(page),
            page_size: String(PAGE_SIZE),
        });
        if (category) params.set("category", category);
        if (action) params.set("action", action);
        if (actor) params.set("actor", actor);
        if (targetType) params.set("target_type", targetType);
        if (targetId) params.set("target_id", targetId);
        if (query) params.set("query", query);
        if (fromDate) params.set("from", `${fromDate}T00:00:00`);
        if (toDate) params.set("to", `${toDate}T23:59:59`);

        const loadEvents = async () => {
            setLoading(true);
            try {
                const response = await apiFetch(`/api/audit-logs?${params.toString()}`);
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data?.message || "Failed to load audit logs");
                }
                if (cancelled) {
                    return;
                }
                setEvents(Array.isArray(data?.events) ? data.events : []);
                setPages(Number(data?.pages || 1));
                setTotal(Number(data?.total || 0));
                setError(null);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Failed to load audit logs");
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        };

        void loadMeta();
        void loadEvents();

        return () => {
            cancelled = true;
        };
    }, [canView, page, category, action, actor, targetType, targetId, query, fromDate, toDate]);

    const openDetails = async (event: AuditEvent) => {
        setSelectedEvent(event);
        setDetailError(null);
        try {
            const response = await apiFetch(`/api/audit-logs/${event.id}`);
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.message || "Failed to load audit event");
            }
            setSelectedEvent(data?.event || event);
        } catch (err) {
            setDetailError(err instanceof Error ? err.message : "Failed to load audit event");
        }
    };

    const resetFilters = () => {
        setCategory("");
        setAction("");
        setActor("");
        setTargetType("");
        setTargetId("");
        setQuery("");
        setFromDate("");
        setToDate("");
        setPage(1);
    };

    if (!canView) {
        return (
            <section className="rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                <h2 className="m-0 text-xl font-semibold text-slate-900">Audit Logs</h2>
                <p className="mb-0 mt-2 text-sm text-red-700">You do not have permission to view audit logs.</p>
            </section>
        );
    }

    const filterChanged =
        Boolean(category || action || actor || targetType || targetId || query || fromDate || toDate);

    return (
        <section className="space-y-4">
            <div className="rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                    <div>
                        <h2 className="m-0 text-xl font-semibold text-slate-900">Audit Logs</h2>
                        <p className="mb-0 mt-1 text-sm text-slate-500">
                            Administrators and moderators with audit access can review privileged activity here.
                        </p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700">
                        {total} events
                    </span>
                </div>

                <form
                    className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4"
                    onSubmit={(event) => {
                        event.preventDefault();
                        setPage(1);
                    }}
                >
                    <label className="flex flex-col gap-1 text-sm text-slate-700">
                        Search
                        <input
                            type="search"
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                            placeholder="Actor, action, target"
                            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                        />
                    </label>

                    <label className="flex flex-col gap-1 text-sm text-slate-700">
                        Category
                        <select
                            value={category}
                            onChange={(event) => setCategory(event.target.value)}
                            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                        >
                            <option value="">All categories</option>
                            {meta.categories.map((item) => (
                                <option key={item.value} value={item.value}>
                                    {item.label}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label className="flex flex-col gap-1 text-sm text-slate-700">
                        Action
                        <select
                            value={action}
                            onChange={(event) => setAction(event.target.value)}
                            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                        >
                            <option value="">All actions</option>
                            {meta.actions.map((item) => (
                                <option key={item.value} value={item.value}>
                                    {item.label}
                                </option>
                            ))}
                        </select>
                    </label>

                    <label className="flex flex-col gap-1 text-sm text-slate-700">
                        Actor
                        <input
                            type="text"
                            value={actor}
                            onChange={(event) => setActor(event.target.value)}
                            placeholder="Username"
                            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                        />
                    </label>

                    <label className="flex flex-col gap-1 text-sm text-slate-700">
                        Target type
                        <input
                            type="text"
                            value={targetType}
                            onChange={(event) => setTargetType(event.target.value)}
                            placeholder="dm_user, discord_server"
                            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                        />
                    </label>

                    <label className="flex flex-col gap-1 text-sm text-slate-700">
                        Target ID
                        <input
                            type="text"
                            value={targetId}
                            onChange={(event) => setTargetId(event.target.value)}
                            placeholder="Discord snowflake or ID"
                            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                        />
                    </label>

                    <label className="flex flex-col gap-1 text-sm text-slate-700">
                        From
                        <input
                            type="date"
                            value={fromDate}
                            onChange={(event) => setFromDate(event.target.value)}
                            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                        />
                    </label>

                    <label className="flex flex-col gap-1 text-sm text-slate-700">
                        To
                        <input
                            type="date"
                            value={toDate}
                            onChange={(event) => setToDate(event.target.value)}
                            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900"
                        />
                    </label>

                    <div className="flex items-end gap-2 sm:col-span-2 lg:col-span-4">
                        <button
                            type="submit"
                            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white"
                        >
                            Apply filters
                        </button>
                        <button
                            type="button"
                            onClick={resetFilters}
                            disabled={!filterChanged}
                            className="rounded-md border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            Reset
                        </button>
                    </div>
                </form>
            </div>

            <div className="rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                {loading && (
                    <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                        Loading audit events...
                    </p>
                )}
                {!loading && error && (
                    <p className="m-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
                )}
                {!loading && !error && events.length === 0 && (
                    <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                        No audit events match these filters.
                    </p>
                )}

                {!loading && !error && events.length > 0 && (
                    <div className="overflow-x-auto">
                        <table className="min-w-full border-collapse text-left text-sm">
                            <thead>
                                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
                                    <th className="px-2 py-2 font-semibold">Timestamp</th>
                                    <th className="px-2 py-2 font-semibold">Actor</th>
                                    <th className="px-2 py-2 font-semibold">Action</th>
                                    <th className="px-2 py-2 font-semibold">Category</th>
                                    <th className="px-2 py-2 font-semibold">Target</th>
                                    <th className="px-2 py-2 font-semibold" />
                                </tr>
                            </thead>
                            <tbody>
                                {events.map((event) => (
                                    <tr key={event.id} className="border-b border-slate-100 align-top">
                                        <td className="whitespace-nowrap px-2 py-2 text-slate-600">
                                            {formatTimestamp(event.created_at)}
                                        </td>
                                        <td className="px-2 py-2">
                                            <div className="font-semibold text-slate-900">{event.actor_username}</div>
                                            <div className="text-xs text-slate-500">{event.actor_role}</div>
                                        </td>
                                        <td className="px-2 py-2">
                                            <div className="font-medium text-slate-800">
                                                {actionLabels[event.action] || event.action}
                                            </div>
                                            <div className="text-xs text-slate-500">{event.action}</div>
                                        </td>
                                        <td className="px-2 py-2 text-slate-600">
                                            {categoryLabels[event.category] || event.category || "—"}
                                        </td>
                                        <td className="px-2 py-2 text-slate-600">
                                            {event.target_type || event.target_id ? (
                                                <>
                                                    <div>{event.target_type || "—"}</div>
                                                    <div className="break-all text-xs text-slate-500">{event.target_id || "—"}</div>
                                                </>
                                            ) : (
                                                "—"
                                            )}
                                        </td>
                                        <td className="px-2 py-2 text-right">
                                            <button
                                                type="button"
                                                onClick={() => void openDetails(event)}
                                                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 hover:bg-slate-100"
                                            >
                                                Details
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}

                <div className="mt-4 flex flex-wrap items-center justify-between gap-2 text-sm text-slate-600">
                    <span>
                        Page {page} of {pages}
                    </span>
                    <div className="flex gap-2">
                        <button
                            type="button"
                            disabled={page <= 1 || loading}
                            onClick={() => setPage((value) => Math.max(1, value - 1))}
                            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            Previous
                        </button>
                        <button
                            type="button"
                            disabled={page >= pages || loading}
                            onClick={() => setPage((value) => Math.min(pages, value + 1))}
                            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-semibold text-slate-700 disabled:cursor-not-allowed disabled:opacity-60"
                        >
                            Next
                        </button>
                    </div>
                </div>
            </div>

            {selectedEvent && (
                <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/40 p-4">
                    <div className="max-h-[85vh] w-full max-w-2xl overflow-y-auto rounded-2xl bg-white p-5 shadow-xl">
                        <div className="mb-3 flex items-start justify-between gap-3">
                            <div>
                                <h3 className="m-0 text-lg font-semibold text-slate-900">
                                    {actionLabels[selectedEvent.action] || selectedEvent.action}
                                </h3>
                                <p className="mb-0 mt-1 text-sm text-slate-500">
                                    Event #{selectedEvent.id} • {formatTimestamp(selectedEvent.created_at)}
                                </p>
                            </div>
                            <button
                                type="button"
                                onClick={() => setSelectedEvent(null)}
                                className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-100"
                            >
                                Close
                            </button>
                        </div>

                        {detailError && (
                            <p className="m-0 mb-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                                {detailError}
                            </p>
                        )}

                        <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
                            <div>
                                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Actor</dt>
                                <dd className="m-0 text-slate-800">
                                    {selectedEvent.actor_username} ({selectedEvent.actor_role})
                                </dd>
                            </div>
                            <div>
                                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Account ID</dt>
                                <dd className="m-0 text-slate-800">{formatValue(selectedEvent.actor_account_id)}</dd>
                            </div>
                            <div>
                                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Category</dt>
                                <dd className="m-0 text-slate-800">
                                    {categoryLabels[selectedEvent.category] || selectedEvent.category}
                                </dd>
                            </div>
                            <div>
                                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Action</dt>
                                <dd className="m-0 break-all text-slate-800">{selectedEvent.action}</dd>
                            </div>
                            <div>
                                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Target type</dt>
                                <dd className="m-0 text-slate-800">{formatValue(selectedEvent.target_type)}</dd>
                            </div>
                            <div>
                                <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">Target ID</dt>
                                <dd className="m-0 break-all text-slate-800">{formatValue(selectedEvent.target_id)}</dd>
                            </div>
                        </dl>

                        <div className="mt-4">
                            <h4 className="m-0 text-sm font-semibold text-slate-800">Metadata</h4>
                            {Object.keys(selectedEvent.metadata || {}).length === 0 ? (
                                <p className="mb-0 mt-1 text-sm text-slate-500">No metadata recorded.</p>
                            ) : (
                                <dl className="mt-2 grid grid-cols-1 gap-2 text-sm sm:grid-cols-2">
                                    {Object.entries(selectedEvent.metadata).map(([key, value]) => (
                                        <div key={key} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
                                            <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">{key}</dt>
                                            <dd className="m-0 break-all text-slate-800">{formatValue(value)}</dd>
                                        </div>
                                    ))}
                                </dl>
                            )}
                        </div>
                    </div>
                </div>
            )}
        </section>
    );
}

export default AuditLogs;
