import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { apiFetch } from "../../api";

type Channel = {
    id: string;
    name: string;
    type: number;
    parent_id: string | null;
};

type MouseTrapProps = {
    serverId: string | null;
    channels: Channel[];
};

export function MouseTrap({ serverId, channels }: MouseTrapProps) {
    const [selectedChannelId, setSelectedChannelId] = useState("none");
    const [kickCount, setKickCount] = useState(0);
    const [loading, setLoading] = useState(false);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [status, setStatus] = useState<string | null>(null);
    const [armedChannelId, setArmedChannelId] = useState<string | null>(null);

    useEffect(() => {
        if (!serverId) {
            setSelectedChannelId("none");
            setKickCount(0);
            setArmedChannelId(null);
            setError(null);
            setStatus(null);
            return;
        }

        let cancelled = false;

        const loadConfig = async () => {
            setLoading(true);
            try {
                const response = await apiFetch(`/api/servers/${serverId}/mousetrap`);
                const data = await response.json().catch(() => ({}));
                if (!response.ok) {
                    throw new Error(data?.message || "Failed to load MouseTrap config");
                }

                const config = data?.config || null;
                if (cancelled) {
                    return;
                }

                const nextChannelId = config?.channel_id || "none";
                setSelectedChannelId(nextChannelId);
                setArmedChannelId(nextChannelId === "none" ? null : nextChannelId);
                setKickCount(Number(config?.kick_count || 0));
                setError(null);
            } catch (err) {
                if (!cancelled) {
                    setError(err instanceof Error ? err.message : "Unable to load MouseTrap config");
                }
            } finally {
                if (!cancelled) {
                    setLoading(false);
                }
            }
        };

        loadConfig();

        return () => {
            cancelled = true;
        };
    }, [serverId]);

    const saveChannel = async (nextChannelId: string) => {
        if (!serverId) {
            return;
        }

        setSaving(true);
        setError(null);
        setStatus(null);

        try {
            const response = await apiFetch(`/api/servers/${serverId}/mousetrap`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({ channel_id: nextChannelId }),
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.message || "Failed to save MouseTrap channel");
            }

            const config = data?.config || null;
            const savedChannelId = config?.channel_id || "none";
            setSelectedChannelId(savedChannelId);
            setArmedChannelId(savedChannelId === "none" ? null : savedChannelId);
            setKickCount(Number(config?.kick_count || 0));
            setStatus(savedChannelId === "none" ? "MouseTrap disabled" : "MouseTrap saved");
        } catch (err) {
            setSelectedChannelId(armedChannelId || "none");
            setError(err instanceof Error ? err.message : "Failed to save MouseTrap channel");
        } finally {
            setSaving(false);
        }
    };

    return (<>
        <div className="mb-3">
            <p className="mb-1 mt-0 text-sm font-semibold text-slate-900">MouseTrap</p>
            <p className="m-0 text-sm text-slate-600">Automated moderation actions on a member that is sending messages on a specific text channel</p>

            <div className="mt-2 flex items-center gap-2">
                <select
                    value={selectedChannelId}
                    onChange={(event) => {
                        const nextChannelId = event.target.value;
                        setSelectedChannelId(nextChannelId);
                        void saveChannel(nextChannelId);
                    }}
                    className="min-w-0 rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                    disabled={!serverId || loading || saving}
                >
                    <option value="none">Select a channel</option>
                    {channels.map((channel) => (
                        <option key={channel.id} value={channel.id}>
                            #{channel.name}
                        </option>
                    ))}
                </select>
                {(loading || saving) && <span className="text-xs text-slate-500">{loading ? "Loading..." : "Saving..."}</span>}
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-slate-600">
                <span className="rounded-full bg-slate-100 px-2 py-1 font-semibold text-slate-700">
                    Kick count: {kickCount}
                </span>
                {armedChannelId && (
                    <span className="rounded-full bg-emerald-50 px-2 py-1 font-semibold text-emerald-700">
                        Armed in #{channels.find((channel) => channel.id === armedChannelId)?.name || armedChannelId}
                    </span>
                )}
                {serverId ? (
                    <Link
                        to={`/servers/${serverId}/mousetrap`}
                        className="rounded-md border border-slate-300 bg-white px-3 py-1.5 font-semibold text-slate-700 hover:bg-slate-100"
                    >
                        Open logs
                    </Link>
                ) : (
                    <span className="rounded-md border border-slate-200 bg-slate-100 px-3 py-1.5 font-semibold text-slate-400">
                        Open logs
                    </span>
                )}
            </div>

            {!serverId && <p className="mt-2 text-xs text-slate-500">Pick a server first to load its channels.</p>}
            {serverId && channels.length === 0 && !loading && (
                <p className="mt-2 text-xs text-slate-500">No channels were found for this server.</p>
            )}
            {error && <p className="mt-2 text-xs text-red-600">{error}</p>}
            {status && <p className="mt-2 text-xs text-emerald-700">{status}</p>}
        </div>
    </>) 
}