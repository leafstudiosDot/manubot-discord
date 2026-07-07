import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

type ServerChannel = {
    id: string;
    name: string;
    type: number;
    parent_id: string | null;
};

type Server = {
    id: string;
    name: string;
    channels?: ServerChannel[];
};

type MouseTrapLog = {
    id: number;
    guild_id: string;
    channel_id: string;
    user_id: string;
    content: string;
    attachments: Array<{
        filename?: string;
        url?: string;
        proxy_url?: string;
        content_type?: string;
    }>;
    occurred_at: string;
    created_at: string;
    author: {
        id: string;
        username: string;
        global_name: string | null;
        display_name: string;
        discriminator: string | null;
        avatar_url: string | null;
        bot: boolean;
    };
};

function MouseTrapRoute() {
    const { serverId } = useParams();
    const [server, setServer] = useState<Server | null>(null);
    const [logs, setLogs] = useState<MouseTrapLog[]>([]);
    const [kickCount, setKickCount] = useState(0);
    const [channelId, setChannelId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        if (!serverId) {
            setLoading(false);
            setError("Missing server id");
            return;
        }

        let cancelled = false;

        const load = async () => {
            setLoading(true);
            try {
                const [serversResponse, logsResponse] = await Promise.all([
                    fetch("/api/servers"),
                    fetch(`/api/servers/${serverId}/mousetrap/logs?limit=100`),
                ]);

                const serversData = await serversResponse.json().catch(() => ({}));
                const logsData = await logsResponse.json().catch(() => ({}));

                if (!serversResponse.ok) {
                    throw new Error(serversData?.message || "Failed to load server details");
                }

                if (!logsResponse.ok) {
                    throw new Error(logsData?.message || "Failed to load MouseTrap logs");
                }

                if (cancelled) {
                    return;
                }

                const nextServer = Array.isArray(serversData?.servers)
                    ? serversData.servers.find((item: Server) => item.id === serverId) || null
                    : null;
                const nextConfig = logsData?.config || null;
                const nextLogs = Array.isArray(logsData?.logs) ? logsData.logs : [];

                setServer(nextServer);
                setLogs(nextLogs);
                setKickCount(Number(nextConfig?.kick_count || 0));
                setChannelId(nextConfig?.channel_id || null);
                setError(null);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Unable to load MouseTrap logs");
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        };

        load();

        return () => {
            cancelled = true;
        };
    }, [serverId]);

    const selectedChannelName = server?.channels?.find((channel) => channel.id === channelId)?.name || null;

    return (
        <section className="mb-4 rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
            <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                    <h2 className="m-0 text-xl font-semibold text-slate-900">MouseTrap Logs</h2>
                    <p className="mb-0 mt-1 text-sm text-slate-500">
                        {server ? server.name : "Selected server"}
                        {selectedChannelName ? ` • #${selectedChannelName}` : ""}
                    </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700">
                        Kick count: {kickCount}
                    </span>
                    <Link
                        to="/servers"
                        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-100"
                    >
                        Back to Servers
                    </Link>
                </div>
            </div>

            {loading && (
                <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                    Loading MouseTrap logs...
                </p>
            )}

            {!loading && error && <p className="m-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

            {!loading && !error && logs.length === 0 && (
                <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                    No MouseTrap logs captured yet.
                </p>
            )}

            {!loading && !error && logs.length > 0 && (
                <ul className="m-0 list-none space-y-2 p-0">
                    {logs.map((log) => (
                        <li key={log.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                            <div className="flex items-start gap-3">
                                {log.author?.avatar_url ? (
                                    <img src={log.author.avatar_url} alt={log.author.display_name} className="h-10 w-10 rounded-full object-cover" />
                                ) : (
                                    <div className="flex h-10 w-10 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-600">
                                        {log.author?.display_name?.slice(0, 1).toUpperCase() || "?"}
                                    </div>
                                )}

                                <div className="min-w-0 flex-1">
                                    <div className="flex flex-wrap items-center justify-between gap-2">
                                        <div>
                                            <p className="m-0 text-sm font-semibold text-slate-900">{log.author?.display_name || log.author?.username || log.user_id}</p>
                                            <p className="m-0 text-xs text-slate-500">@{log.author?.username || log.user_id} • {new Date(log.occurred_at).toLocaleString()}</p>
                                        </div>
                                        <span className="rounded-full bg-white px-2 py-1 text-xs font-semibold text-slate-600">
                                            User ID: {log.user_id}
                                        </span>
                                    </div>

                                    {log.content && <p className="mt-2 whitespace-pre-wrap break-words text-sm text-slate-700">{log.content}</p>}

                                    {Array.isArray(log.attachments) && log.attachments.length > 0 && (
                                        <ul className="mt-2 list-disc pl-5 text-xs text-slate-600">
                                            {log.attachments.map((attachment, index) => (
                                                <li key={`${log.id}-${index}`}>
                                                    {attachment.url ? (
                                                        <a href={attachment.url} target="_blank" rel="noreferrer" className="text-slate-700 underline">
                                                            {attachment.filename || "attachment"}
                                                        </a>
                                                    ) : (
                                                        attachment.filename || "attachment"
                                                    )}
                                                </li>
                                            ))}
                                        </ul>
                                    )}
                                </div>
                            </div>
                        </li>
                    ))}
                </ul>
            )}
        </section>
    );
}

export default MouseTrapRoute;