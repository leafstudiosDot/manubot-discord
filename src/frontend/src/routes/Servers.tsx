import { useEffect, useState } from "react";

type Server = {
    id: string;
    name: string;
    icon_url: string | null;
    owner: boolean;
    permissions: string | null;
    features: string[];
};

type PermissionFlag = {
    bit: bigint;
    label: string;
};

const PERMISSION_FLAGS: PermissionFlag[] = [
    { bit: 1n << 0n, label: "Create Instant Invite" },
    { bit: 1n << 1n, label: "Kick Members" },
    { bit: 1n << 2n, label: "Ban Members" },
    { bit: 1n << 3n, label: "Administrator" },
    { bit: 1n << 4n, label: "Manage Channels" },
    { bit: 1n << 5n, label: "Manage Guild" },
    { bit: 1n << 6n, label: "Add Reactions" },
    { bit: 1n << 7n, label: "View Audit Log" },
    { bit: 1n << 8n, label: "Priority Speaker" },
    { bit: 1n << 9n, label: "Stream" },
    { bit: 1n << 10n, label: "View Channels" },
    { bit: 1n << 11n, label: "Send Messages" },
    { bit: 1n << 12n, label: "Send TTS Messages" },
    { bit: 1n << 13n, label: "Manage Messages" },
    { bit: 1n << 14n, label: "Embed Links" },
    { bit: 1n << 15n, label: "Attach Files" },
    { bit: 1n << 16n, label: "Read Message History" },
    { bit: 1n << 17n, label: "Mention Everyone" },
    { bit: 1n << 18n, label: "Use External Emojis" },
    { bit: 1n << 19n, label: "View Guild Insights" },
    { bit: 1n << 20n, label: "Connect" },
    { bit: 1n << 21n, label: "Speak" },
    { bit: 1n << 22n, label: "Mute Members" },
    { bit: 1n << 23n, label: "Deafen Members" },
    { bit: 1n << 24n, label: "Move Members" },
    { bit: 1n << 25n, label: "Use Voice Activity" },
    { bit: 1n << 26n, label: "Change Nickname" },
    { bit: 1n << 27n, label: "Manage Nicknames" },
    { bit: 1n << 28n, label: "Manage Roles" },
    { bit: 1n << 29n, label: "Manage Webhooks" },
    { bit: 1n << 30n, label: "Manage Emojis and Stickers" },
    { bit: 1n << 31n, label: "Use Application Commands" },
    { bit: 1n << 32n, label: "Request to Speak" },
    { bit: 1n << 33n, label: "Manage Events" },
    { bit: 1n << 34n, label: "Manage Threads" },
    { bit: 1n << 35n, label: "Create Public Threads" },
    { bit: 1n << 36n, label: "Create Private Threads" },
    { bit: 1n << 37n, label: "Use External Stickers" },
    { bit: 1n << 38n, label: "Send Messages in Threads" },
    { bit: 1n << 39n, label: "Use Embedded Activities" },
    { bit: 1n << 40n, label: "Moderate Members" },
    { bit: 1n << 41n, label: "View Creator Monetization Analytics" },
    { bit: 1n << 42n, label: "Use Soundboard" },
    { bit: 1n << 43n, label: "Create Guild Expressions" },
    { bit: 1n << 44n, label: "Create Events" },
    { bit: 1n << 45n, label: "Use External Sounds" },
    { bit: 1n << 46n, label: "Send Voice Messages" },
    { bit: 1n << 47n, label: "Send Polls" },
    { bit: 1n << 49n, label: "Use External Apps" },
];

function decodePermissions(permissions: string | null): string[] {
    if (!permissions) {
        return [];
    }

    let value: bigint;
    try {
        value = BigInt(permissions);
    } catch {
        return [];
    }

    return PERMISSION_FLAGS.filter((flag) => (value & flag.bit) === flag.bit).map((flag) => flag.label);
}

function Servers({ loading, canView }) {
    const [servers, setServers] = useState<Server[]>([]);
    const [selectedServerId, setSelectedServerId] = useState<string | null>(null);
    const [view, setView] = useState<"list" | "detail">("list");
    const [fetching, setFetching] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const selectedServer = servers.find((server) => server.id === selectedServerId) || null;
    const selectedPermissions = decodePermissions(selectedServer?.permissions || null);

    useEffect(() => {
        if (!canView) {
            setFetching(false);
            setServers([]);
            return;
        }

        let isCancelled = false;

        const loadServers = async () => {
            try {
                const response = await fetch("/api/servers");
                if (!response.ok) {
                    throw new Error("Failed to load server list");
                }

                const data = await response.json();
                if (!isCancelled) {
                    const nextServers = Array.isArray(data?.servers) ? data.servers : [];
                    setServers(nextServers);

                    if (!nextServers.length) {
                        setSelectedServerId(null);
                        setView("list");
                    } else {
                        setSelectedServerId((current) => {
                            if (current && nextServers.some((server: Server) => server.id === current)) {
                                return current;
                            }
                            return nextServers[0].id;
                        });
                    }

                    setError(null);
                }
            } catch (err) {
                if (!isCancelled) {
                    setError(err instanceof Error ? err.message : "Unable to load server list");
                }
            } finally {
                if (!isCancelled) {
                    setFetching(false);
                }
            }
        };

        loadServers();
        const interval = window.setInterval(loadServers, 7000);

        return () => {
            isCancelled = true;
            window.clearInterval(interval);
        };
    }, [canView]);

    if (!canView) {
        return (
            <section className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                <h2 className="m-0 text-xl font-semibold text-amber-900">Server List</h2>
                <p className="mb-0 mt-2 text-sm text-amber-800">You do not have permission to view servers.</p>
            </section>
        );
    }

    return (
        <>
            <section className="mb-4 rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                <div className="mb-4 flex items-center justify-between gap-3">
                    <div>
                        <h2 className="m-0 text-xl font-semibold text-slate-900">Server List</h2>
                        <p className="mb-0 mt-1 text-sm text-slate-500">Guilds where the bot account is currently a member.</p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700">
                        {servers.length} total
                    </span>
                </div>

                {(loading || fetching) && (
                    <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                        Loading servers...
                    </p>
                )}

                {!loading && !fetching && error && (
                    <p className="m-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
                )}

                {!loading && !fetching && !error && servers.length === 0 && (
                    <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                        No servers found for this bot account.
                    </p>
                )}

                {!loading && !fetching && !error && servers.length > 0 && (
                    <>
                        {view === "list" && (
                            <ul className="m-0 list-none space-y-2 p-0">
                                {servers.map((server) => (
                                    <li key={server.id}>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setSelectedServerId(server.id);
                                                setView("detail");
                                            }}
                                            className="w-full rounded-lg border border-slate-200 bg-slate-50 p-3 text-left transition hover:border-slate-300 hover:bg-white"
                                        >
                                            <div className="mb-2 flex items-center gap-2">
                                                {server.icon_url ? (
                                                    <img src={server.icon_url} alt={server.name} className="h-8 w-8 rounded-md object-cover" />
                                                ) : (
                                                    <div className="flex h-8 w-8 items-center justify-center rounded-md bg-slate-200 text-xs font-bold text-slate-600">
                                                        {server.name.slice(0, 1).toUpperCase()}
                                                    </div>
                                                )}
                                                <p className="m-0 truncate text-sm font-semibold text-slate-900">{server.name}</p>
                                            </div>
                                            <p className="m-0 text-xs text-slate-500">ID: {server.id}</p>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}

                        {view === "detail" && (
                            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                                <button
                                    type="button"
                                    onClick={() => setView("list")}
                                    className="mb-4 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-100"
                                >
                                    Back to Server List
                                </button>

                                {selectedServer ? (
                                    <>
                                        <div className="mb-3 flex items-center gap-3">
                                            {selectedServer.icon_url ? (
                                                <img src={selectedServer.icon_url} alt={selectedServer.name} className="h-12 w-12 rounded-lg object-cover" />
                                            ) : (
                                                <div className="flex h-12 w-12 items-center justify-center rounded-lg bg-slate-200 text-base font-bold text-slate-600">
                                                    {selectedServer.name.slice(0, 1).toUpperCase()}
                                                </div>
                                            )}
                                            <div>
                                                <h3 className="m-0 text-lg font-semibold text-slate-900">{selectedServer.name}</h3>
                                                <p className="m-0 text-xs text-slate-500">Guild ID: {selectedServer.id}</p>
                                            </div>
                                        </div>

                                        <div className="mb-4 grid gap-2 sm:grid-cols-2">
                                            <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                                                <span className="font-semibold text-slate-900">Bot Owner:</span> {selectedServer.owner ? "Yes" : "No"}
                                            </div>
                                            <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
                                                <span className="font-semibold text-slate-900">Guild Features:</span> {(selectedServer.features || []).length}
                                            </div>
                                        </div>

                                        <div className="mb-3">
                                            <p className="mb-1 mt-0 text-sm font-semibold text-slate-900">Raw Permission Bitset</p>
                                            <p className="m-0 break-all rounded-lg border border-slate-200 bg-white px-3 py-2 font-mono text-xs text-slate-700">
                                                {selectedServer.permissions || "Unavailable"}
                                            </p>
                                        </div>

                                        <div>
                                            <p className="mb-2 mt-0 text-sm font-semibold text-slate-900">Bot Permissions in This Server</p>

                                            {selectedPermissions.length === 0 ? (
                                                <p className="m-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-600">
                                                    No decoded permissions found.
                                                </p>
                                            ) : (
                                                <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-2 xl:grid-cols-3">
                                                    {selectedPermissions.map((permission) => (
                                                        <li key={permission} className="rounded-md border border-slate-200 bg-white px-2 py-1 text-xs text-slate-700">
                                                            {permission}
                                                        </li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>
                                    </>
                                ) : (
                                    <p className="m-0 text-sm text-slate-600">This server is no longer available. Go back and pick another one.</p>
                                )}
                            </div>
                        )}
                    </>
                )}
            </section>
        </>
    );
}

export default Servers;