import { useEffect, useRef, useState } from "react";
import Prompt from "../components/prompt";

type DmUser = {
    user_id: string;
    username: string;
    global_name: string | null;
    display_name: string;
    discriminator: string | null;
    avatar_url: string | null;
    is_bot: boolean;
    message_count: number;
    last_message_preview: string;
    last_event_type: string;
    last_activity: string;
    channel_count: number;
};

type DmHistoryMessage = {
    message_id: string;
    channel_id: string;
    peer_user_id: string;
    author: {
        id: string | null;
        username: string | null;
        display_name: string | null;
        avatar_url: string | null;
        is_bot: boolean;
    };
    content: string;
    attachments: Array<{
        id?: string | number;
        filename?: string;
        url?: string;
        proxy_url?: string;
        content_type?: string;
    }>;
    timestamp: string;
    edited_timestamp: string | null;
};

function buildWsUrl(path: string) {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.host}${path}`;
}

function DirectMessages({ loading }) {
    const [users, setUsers] = useState<DmUser[]>([]);
    const [view, setView] = useState<"list" | "compose">("list");
    const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
    const [fetching, setFetching] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [messageText, setMessageText] = useState("");
    const [files, setFiles] = useState<File[]>([]);
    const [sending, setSending] = useState(false);
    const [sendStatus, setSendStatus] = useState<string | null>(null);
    const [sendError, setSendError] = useState<string | null>(null);
    const [history, setHistory] = useState<DmHistoryMessage[]>([]);
    const [historyLoading, setHistoryLoading] = useState(false);
    const [historyError, setHistoryError] = useState<string | null>(null);
    const [activeMenuMessageId, setActiveMenuMessageId] = useState<string | null>(null);
    const [deletePromptOpen, setDeletePromptOpen] = useState(false);
    const [deleteBusy, setDeleteBusy] = useState(false);
    const [pendingDeleteMessage, setPendingDeleteMessage] = useState<DmHistoryMessage | null>(null);
    const fileInputRef = useRef<HTMLInputElement | null>(null);

    const visibleUsers = users.filter((user) => !user.is_bot);
    const selectedUser = visibleUsers.find((user) => user.user_id === selectedUserId) || null;

    useEffect(() => {
        let isCancelled = false;
        let ws: WebSocket | null = null;
        let reconnectHandle: number | null = null;

        const connect = () => {
            ws = new WebSocket(buildWsUrl("/ws/direct-messages/users?limit=400"));

            ws.onopen = () => {
                if (!isCancelled) {
                    setError(null);
                }
            };

            ws.onmessage = (event) => {
                if (isCancelled) {
                    return;
                }

                try {
                    const data = JSON.parse(event.data);
                    const nextUsers = Array.isArray(data?.users) ? data.users : [];
                    setUsers(nextUsers);

                    const nextVisibleUsers = nextUsers.filter((entry: DmUser) => !entry.is_bot);
                    setSelectedUserId((current) => {
                        if (current && nextVisibleUsers.some((entry: DmUser) => entry.user_id === current)) {
                            return current;
                        }
                        return nextVisibleUsers.length ? nextVisibleUsers[0].user_id : null;
                    });
                    setError(null);
                } catch (err) {
                    setError(err instanceof Error ? err.message : "Invalid direct message websocket payload");
                }

                if (!isCancelled) {
                    setFetching(false);
                }
            };

            ws.onerror = () => {
                if (!isCancelled) {
                    setError("Direct message websocket connection error");
                }
            };

            ws.onclose = () => {
                if (!isCancelled) {
                    reconnectHandle = window.setTimeout(connect, 1500);
                }
            };
        };

        connect();

        return () => {
            isCancelled = true;

            if (reconnectHandle !== null) {
                window.clearTimeout(reconnectHandle);
            }

            if (ws) {
                ws.close();
            }
        };
    }, []);

    const handleFileChange = (event: React.ChangeEvent<HTMLInputElement>) => {
        const picked = event.target.files ? Array.from(event.target.files) : [];
        setFiles(picked);
    };

    const handleSendMessage = async () => {
        if (!selectedUser) {
            setSendError("No user selected");
            return;
        }

        if (!messageText.trim() && files.length === 0) {
            setSendError("Write a message or attach at least one file");
            return;
        }

        setSending(true);
        setSendError(null);
        setSendStatus(null);

        try {
            const formData = new FormData();
            formData.append("user_id", selectedUser.user_id);
            formData.append("content", messageText);

            files.forEach((file) => {
                formData.append("files", file);
            });

            const response = await fetch("/api/direct-messages/send", {
                method: "POST",
                body: formData,
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.message || "Failed to send direct message");
            }

            setSendStatus("Message sent successfully");
            setMessageText("");
            setFiles([]);
            setActiveMenuMessageId(null);
            if (fileInputRef.current) {
                fileInputRef.current.value = "";
            }
        } catch (err) {
            setSendError(err instanceof Error ? err.message : "Failed to send direct message");
        } finally {
            setSending(false);
        }
    };

    useEffect(() => {
        if (view !== "compose" || !selectedUserId) {
            return;
        }

        let cancelled = false;
        let ws: WebSocket | null = null;
        let reconnectHandle: number | null = null;

        const connect = () => {
            setHistoryLoading(true);

            ws = new WebSocket(
                buildWsUrl(`/ws/direct-messages/history?user_id=${encodeURIComponent(selectedUserId)}&limit=150`)
            );

            ws.onopen = () => {
                if (!cancelled) {
                    setHistoryError(null);
                }
            };

            ws.onmessage = (event) => {
                if (cancelled) {
                    return;
                }

                try {
                    const data = JSON.parse(event.data);
                    if (data?.status === "error") {
                        setHistoryError(data?.message || "Failed to load message history");
                        setHistory([]);
                    } else {
                        setHistory(Array.isArray(data?.messages) ? data.messages : []);
                        setHistoryError(null);
                    }
                } catch (err) {
                    setHistoryError(err instanceof Error ? err.message : "Invalid history websocket payload");
                } finally {
                    setHistoryLoading(false);
                }
            };

            ws.onerror = () => {
                if (!cancelled) {
                    setHistoryError("Message history websocket connection error");
                }
            };

            ws.onclose = () => {
                if (!cancelled) {
                    reconnectHandle = window.setTimeout(connect, 1500);
                }
            };
        };

        connect();

        return () => {
            cancelled = true;

            if (reconnectHandle !== null) {
                window.clearTimeout(reconnectHandle);
            }

            if (ws) {
                ws.close();
            }
        };
    }, [selectedUserId, view]);

    const openDeletePrompt = (message: DmHistoryMessage) => {
        setPendingDeleteMessage(message);
        setDeletePromptOpen(true);
    };

    const handleDeleteMessage = async () => {
        if (!pendingDeleteMessage) {
            return;
        }

        setDeleteBusy(true);
        try {
            const response = await fetch(`/api/direct-messages/messages/${encodeURIComponent(pendingDeleteMessage.message_id)}`, {
                method: "DELETE",
            });
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.message || "Failed to delete message");
            }

            setHistory((current) => current.filter((item) => item.message_id !== pendingDeleteMessage.message_id));
            setActiveMenuMessageId(null);
            setSendStatus("Message deleted");
            setSendError(null);
            setDeletePromptOpen(false);
            setPendingDeleteMessage(null);
        } catch (err) {
            setSendError(err instanceof Error ? err.message : "Failed to delete message");
        } finally {
            setDeleteBusy(false);
        }
    };

    return (
        <>
            <section className="mb-4 rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                <div className="mb-4 flex items-center justify-between gap-3">
                    <div>
                        <h2 className="m-0 text-xl font-semibold text-slate-900">Direct Messages by User</h2>
                        <p className="mb-0 mt-1 text-sm text-slate-500">
                            Grouped from captured DM events in the gateway log.
                        </p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700">
                        {visibleUsers.length} users
                    </span>
                </div>

                {(loading || fetching) && (
                    <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                        Loading direct message users from websocket...
                    </p>
                )}

                {!loading && !fetching && error && (
                    <p className="m-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>
                )}

                {!loading && !fetching && !error && visibleUsers.length === 0 && (
                    <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                        No DM events captured yet.
                    </p>
                )}

                {!loading && !fetching && !error && visibleUsers.length > 0 && (
                    <>
                        {view === "list" && (
                            <ul className="m-0 list-none space-y-2 p-0">
                                {visibleUsers.map((user) => (
                                    <li key={user.user_id}>
                                        <button
                                            type="button"
                                            onClick={() => {
                                                setSelectedUserId(user.user_id);
                                                setView("compose");
                                            }}
                                            className="w-full rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-left transition hover:border-slate-300 hover:bg-white"
                                        >
                                            <div className="flex items-center gap-3">
                                                {user.avatar_url ? (
                                                    <img src={user.avatar_url} alt={user.display_name} className="h-9 w-9 rounded-full object-cover" />
                                                ) : (
                                                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-600">
                                                        {user.display_name.slice(0, 1).toUpperCase()}
                                                    </div>
                                                )}
                                                <div className="min-w-0 flex-1">
                                                    <p className="m-0 truncate text-sm font-semibold text-slate-900">{user.display_name}</p>
                                                    <p className="m-0 truncate text-xs text-slate-500">{user.last_message_preview}</p>
                                                </div>
                                                <div className="text-right text-xs text-slate-500">
                                                    <p className="m-0">{user.message_count} msg</p>
                                                    <p className="m-0">{new Date(user.last_activity).toLocaleTimeString()}</p>
                                                </div>
                                            </div>
                                        </button>
                                    </li>
                                ))}
                            </ul>
                        )}

                        {view === "compose" && (
                            <div className="rounded-xl border border-slate-200 bg-slate-50 p-4">
                                <button
                                    type="button"
                                    onClick={() => setView("list")}
                                    className="mb-4 rounded-md border border-slate-300 bg-white px-3 py-1.5 text-sm font-semibold text-slate-700 hover:bg-slate-100"
                                >
                                    Back to User List
                                </button>

                                {selectedUser ? (
                                    <>
                                        <div className="mb-3 flex items-center gap-3">
                                            {selectedUser.avatar_url ? (
                                                <img src={selectedUser.avatar_url} alt={selectedUser.display_name} className="h-12 w-12 rounded-full object-cover" />
                                            ) : (
                                                <div className="flex h-12 w-12 items-center justify-center rounded-full bg-slate-200 text-sm font-semibold text-slate-600">
                                                    {selectedUser.display_name.slice(0, 1).toUpperCase()}
                                                </div>
                                            )}
                                            <div>
                                                <h3 className="m-0 text-lg font-semibold text-slate-900">{selectedUser.display_name}</h3>
                                                <p className="m-0 text-xs text-slate-500">@{selectedUser.username}</p>
                                            </div>
                                        </div>

                                        <div className="mb-4">
                                            <p className="mb-2 mt-0 text-sm font-semibold text-slate-900">Message History</p>

                                            {historyLoading && (
                                                <p className="m-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                                                    Loading history...
                                                </p>
                                            )}

                                            {historyError && (
                                                <p className="m-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                                                    {historyError}
                                                </p>
                                            )}

                                            {!historyLoading && !historyError && history.length === 0 && (
                                                <p className="m-0 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                                                    No saved DM history yet for this user.
                                                </p>
                                            )}

                                            {!historyLoading && !historyError && history.length > 0 && (
                                                <ul className="m-0 max-h-72 list-none space-y-2 overflow-y-auto p-0">
                                                    {history.map((message) => {
                                                        const isBotMessage = Boolean(message.author?.is_bot);
                                                        const authorName =
                                                            message.author?.display_name || message.author?.username || (isBotMessage ? "Bot" : "User");

                                                        return (
                                                            <li key={message.message_id} className="rounded-lg border border-slate-200 bg-white p-2">
                                                                <div className="mb-1 flex items-start justify-between gap-2">
                                                                    <div>
                                                                        <p className="m-0 text-xs font-semibold text-slate-800">
                                                                            {authorName} {isBotMessage ? "(Bot)" : ""}
                                                                        </p>
                                                                        <p className="m-0 text-[11px] text-slate-500">
                                                                            {new Date(message.timestamp).toLocaleString()}
                                                                        </p>
                                                                    </div>
                                                                    <div className="relative">
                                                                        <button
                                                                            type="button"
                                                                            onClick={() =>
                                                                                setActiveMenuMessageId((current) =>
                                                                                    current === message.message_id ? null : message.message_id
                                                                                )
                                                                            }
                                                                            className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-700 hover:bg-slate-50"
                                                                        >
                                                                            More
                                                                        </button>

                                                                        {activeMenuMessageId === message.message_id && isBotMessage && (
                                                                            <div className="absolute right-0 z-10 mt-1 min-w-24 rounded-md border border-slate-200 bg-white p-1 shadow">
                                                                                <button
                                                                                    type="button"
                                                                                    onClick={() => openDeletePrompt(message)}
                                                                                    className="w-full rounded px-2 py-1 text-left text-xs font-semibold text-red-700 hover:bg-red-50"
                                                                                >
                                                                                    Delete
                                                                                </button>
                                                                            </div>
                                                                        )}
                                                                    </div>
                                                                </div>

                                                                {message.content && (
                                                                    <p className="m-0 whitespace-pre-wrap break-words text-xs text-slate-700">{message.content}</p>
                                                                )}

                                                                {Array.isArray(message.attachments) && message.attachments.length > 0 && (
                                                                    <ul className="mb-0 mt-1 list-disc pl-4 text-[11px] text-slate-600">
                                                                        {message.attachments.map((attachment, index) => (
                                                                            <li key={`${message.message_id}-${index}`}>
                                                                                {attachment.url ? (
                                                                                    <a
                                                                                        href={attachment.url}
                                                                                        target="_blank"
                                                                                        rel="noreferrer"
                                                                                        className="text-slate-700 underline"
                                                                                    >
                                                                                        {attachment.filename || "attachment"}
                                                                                    </a>
                                                                                ) : (
                                                                                    attachment.filename || "attachment"
                                                                                )}
                                                                            </li>
                                                                        ))}
                                                                    </ul>
                                                                )}
                                                            </li>
                                                        );
                                                    })}
                                                </ul>
                                            )}
                                        </div>

                                        <div className="mb-3">
                                            <label className="mb-1 block text-sm font-semibold text-slate-900" htmlFor="dm-content">
                                                Message
                                            </label>
                                            <textarea
                                                id="dm-content"
                                                value={messageText}
                                                onChange={(event) => setMessageText(event.target.value)}
                                                rows={5}
                                                className="w-full resize-y rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 outline-none ring-slate-400 focus:border-slate-400 focus:ring-2"
                                                placeholder="Write a direct message..."
                                            />
                                        </div>

                                        <div className="mb-3">
                                            <label className="mb-1 block text-sm font-semibold text-slate-900" htmlFor="dm-files">
                                                Media / Files
                                            </label>
                                            <input
                                                ref={fileInputRef}
                                                id="dm-files"
                                                type="file"
                                                multiple
                                                onChange={handleFileChange}
                                                className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-700"
                                            />
                                            {files.length > 0 && (
                                                <ul className="mb-0 mt-2 list-disc pl-5 text-xs text-slate-600">
                                                    {files.map((file) => (
                                                        <li key={`${file.name}-${file.size}`}>{file.name}</li>
                                                    ))}
                                                </ul>
                                            )}
                                        </div>

                                        {sendError && (
                                            <p className="mb-3 mt-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{sendError}</p>
                                        )}

                                        {sendStatus && (
                                            <p className="mb-3 mt-0 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                                                {sendStatus}
                                            </p>
                                        )}

                                        <button
                                            type="button"
                                            onClick={handleSendMessage}
                                            disabled={sending}
                                            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
                                        >
                                            {sending ? "Sending..." : "Send DM"}
                                        </button>
                                    </>
                                ) : (
                                    <p className="m-0 text-sm text-slate-600">This user is no longer available in the list.</p>
                                )}
                            </div>
                        )}
                    </>
                )}
            </section>

            <Prompt
                open={deletePromptOpen}
                title="Delete Direct Message"
                message="This will delete the selected bot message from Discord and your saved SQLite history. Continue?"
                confirmText="Delete"
                cancelText="Cancel"
                danger
                busy={deleteBusy}
                onCancel={() => {
                    if (deleteBusy) {
                        return;
                    }
                    setDeletePromptOpen(false);
                    setPendingDeleteMessage(null);
                }}
                onConfirm={handleDeleteMessage}
            />
        </>
    );
}

export default DirectMessages;