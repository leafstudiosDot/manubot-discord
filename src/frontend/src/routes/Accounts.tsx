import { useEffect, useState } from "react";

const MODERATOR_PERMISSIONS = [
    { key: "events_view", label: "View gateway events" },
    { key: "servers_view", label: "View server list" },
    { key: "direct_messages_read", label: "Read direct messages" },
    { key: "direct_messages_send", label: "Send direct messages" },
    { key: "direct_messages_delete", label: "Delete bot direct messages" },
];

type Account = {
    id: number;
    username: string;
    role: "admin" | "moderator";
    permissions: Record<string, boolean>;
    created_at: string;
    updated_at: string;
};

type AccountsProps = {
    role: "superadmin" | "admin" | "moderator";
    username: string;
    canView: boolean;
    canCreate: boolean;
    canManageModerators: boolean;
};

function Accounts({ role, username, canView, canCreate, canManageModerators }: AccountsProps) {
    const [accounts, setAccounts] = useState<Account[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const [createUsername, setCreateUsername] = useState("");
    const [createPassword, setCreatePassword] = useState("");
    const [createRole, setCreateRole] = useState<"admin" | "moderator">("moderator");
    const [createBusy, setCreateBusy] = useState(false);
    const [createMessage, setCreateMessage] = useState<string | null>(null);

    const [saveBusyId, setSaveBusyId] = useState<number | null>(null);
    const [saveMessage, setSaveMessage] = useState<string | null>(null);

    const [ownCurrentPassword, setOwnCurrentPassword] = useState("");
    const [ownNewPassword, setOwnNewPassword] = useState("");
    const [ownConfirmPassword, setOwnConfirmPassword] = useState("");
    const [ownBusy, setOwnBusy] = useState(false);
    const [ownMessage, setOwnMessage] = useState<string | null>(null);

    const [passwordResetDrafts, setPasswordResetDrafts] = useState<Record<number, string>>({});
    const [passwordResetBusyId, setPasswordResetBusyId] = useState<number | null>(null);
    const [passwordResetMessage, setPasswordResetMessage] = useState<string | null>(null);

    const loadAccounts = async () => {
        if (!canView) {
            setLoading(false);
            return;
        }

        setLoading(true);
        try {
            const response = await fetch("/api/accounts");
            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.message || "Failed to load accounts");
            }

            const rows = Array.isArray(data?.accounts) ? data.accounts : [];
            setAccounts(rows);
            setError(null);
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load accounts");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadAccounts();
    }, [canView]);

    const handleCreateAccount = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();
        setCreateBusy(true);
        setCreateMessage(null);

        try {
            const response = await fetch("/api/accounts", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    username: createUsername,
                    password: createPassword,
                    role: createRole,
                }),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.message || "Failed to create account");
            }

            setCreateMessage(`Created ${data?.account?.role || createRole} account: ${data?.account?.username || createUsername}`);
            setCreateUsername("");
            setCreatePassword("");
            await loadAccounts();
        } catch (err) {
            setCreateMessage(err instanceof Error ? err.message : "Failed to create account");
        } finally {
            setCreateBusy(false);
        }
    };

    const toggleModeratorPermission = (accountId: number, permission: string, checked: boolean) => {
        setAccounts((current) =>
            current.map((account) =>
                account.id === accountId
                    ? {
                        ...account,
                        permissions: {
                            ...(account.permissions || {}),
                            [permission]: checked,
                        },
                    }
                    : account
            )
        );
    };

    const saveModeratorPermissions = async (account: Account) => {
        setSaveBusyId(account.id);
        setSaveMessage(null);

        try {
            const response = await fetch(`/api/accounts/${account.id}/permissions`, {
                method: "PATCH",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    permissions: account.permissions,
                }),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.message || "Failed to update permissions");
            }

            setSaveMessage(`Updated permissions for ${account.username}`);
            await loadAccounts();
        } catch (err) {
            setSaveMessage(err instanceof Error ? err.message : "Failed to update permissions");
        } finally {
            setSaveBusyId(null);
        }
    };

    const handleOwnPasswordChange = async (event: React.FormEvent<HTMLFormElement>) => {
        event.preventDefault();

        if (role === "superadmin") {
            setOwnMessage("Superadmin password cannot be changed from this panel.");
            return;
        }

        if (!ownCurrentPassword || !ownNewPassword) {
            setOwnMessage("Current password and new password are required.");
            return;
        }

        if (ownNewPassword !== ownConfirmPassword) {
            setOwnMessage("New password confirmation does not match.");
            return;
        }

        setOwnBusy(true);
        setOwnMessage(null);

        try {
            const response = await fetch("/api/accounts/change-own-password", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    current_password: ownCurrentPassword,
                    new_password: ownNewPassword,
                }),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.message || "Failed to change password");
            }

            setOwnCurrentPassword("");
            setOwnNewPassword("");
            setOwnConfirmPassword("");
            setOwnMessage("Password updated successfully. Your current session stays active.");
        } catch (err) {
            setOwnMessage(err instanceof Error ? err.message : "Failed to change password");
        } finally {
            setOwnBusy(false);
        }
    };

    const handleSuperadminPasswordReset = async (account: Account) => {
        const nextPassword = (passwordResetDrafts[account.id] || "").trim();
        if (!nextPassword) {
            setPasswordResetMessage("Please enter a new password before resetting.");
            return;
        }

        setPasswordResetBusyId(account.id);
        setPasswordResetMessage(null);

        try {
            const response = await fetch(`/api/accounts/${account.id}/password`, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    new_password: nextPassword,
                }),
            });

            const data = await response.json().catch(() => ({}));
            if (!response.ok) {
                throw new Error(data?.message || "Failed to reset password");
            }

            setPasswordResetDrafts((current) => ({ ...current, [account.id]: "" }));
            setPasswordResetMessage(
                `Password changed for ${account.username}. Revoked ${data?.account?.revoked_sessions || 0} active session(s).`
            );
            await loadAccounts();
        } catch (err) {
            setPasswordResetMessage(err instanceof Error ? err.message : "Failed to reset password");
        } finally {
            setPasswordResetBusyId(null);
        }
    };

    const canChangeOwnPassword = role === "admin" || role === "moderator";

    return (
        <>
            <section className="mb-4 rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                <h2 className="m-0 text-xl font-semibold text-slate-900">My Account</h2>
                <p className="mb-4 mt-1 text-sm text-slate-500">Signed in as {username} ({role}).</p>

                {canChangeOwnPassword ? (
                    <form className="grid gap-3 sm:grid-cols-2" onSubmit={handleOwnPasswordChange}>
                        <label className="text-sm text-slate-800">
                            <span className="mb-1 block font-semibold">Current Password</span>
                            <input
                                type="password"
                                value={ownCurrentPassword}
                                onChange={(event) => setOwnCurrentPassword(event.target.value)}
                                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                                required
                            />
                        </label>

                        <label className="text-sm text-slate-800">
                            <span className="mb-1 block font-semibold">New Password</span>
                            <input
                                type="password"
                                value={ownNewPassword}
                                onChange={(event) => setOwnNewPassword(event.target.value)}
                                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                                minLength={8}
                                required
                            />
                        </label>

                        <label className="text-sm text-slate-800 sm:col-span-2">
                            <span className="mb-1 block font-semibold">Confirm New Password</span>
                            <input
                                type="password"
                                value={ownConfirmPassword}
                                onChange={(event) => setOwnConfirmPassword(event.target.value)}
                                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                                minLength={8}
                                required
                            />
                        </label>

                        <button
                            type="submit"
                            disabled={ownBusy}
                            className="sm:col-span-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-70"
                        >
                            {ownBusy ? "Updating..." : "Change My Password"}
                        </button>
                    </form>
                ) : (
                    <p className="m-0 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                        Superadmin password cannot be changed from this panel.
                    </p>
                )}

                {ownMessage && (
                    <p className="mb-0 mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                        {ownMessage}
                    </p>
                )}
            </section>

            {!canView && (
                <section className="mb-4 rounded-2xl border border-amber-200 bg-amber-50 p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                    <h2 className="m-0 text-xl font-semibold text-amber-900">Accounts</h2>
                    <p className="mb-0 mt-2 text-sm text-amber-800">You do not have permission to view account management.</p>
                </section>
            )}

            {canView && (
            <section className="mb-4 rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                <div className="mb-4 flex items-center justify-between gap-3">
                    <div>
                        <h2 className="m-0 text-xl font-semibold text-slate-900">Accounts</h2>
                        <p className="mb-0 mt-1 text-sm text-slate-500">Admin and moderator accounts for this panel access.</p>
                    </div>
                    <span className="rounded-full bg-slate-100 px-3 py-1 text-sm font-semibold text-slate-700">
                        {accounts.length} total
                    </span>
                </div>

                {loading && <p className="m-0 text-sm text-slate-600">Loading accounts...</p>}
                {!loading && error && <p className="m-0 text-sm text-red-700">{error}</p>}

                {!loading && !error && (
                    <ul className="m-0 list-none space-y-3 p-0">
                        {accounts.map((account) => (
                            <li key={account.id} className="rounded-xl border border-slate-200 bg-slate-50 p-3">
                                <div className="mb-2 flex items-center justify-between gap-3">
                                    <div>
                                        <p className="m-0 text-sm font-semibold text-slate-900">{account.username}</p>
                                        <p className="m-0 text-xs text-slate-500">Role: {account.role}</p>
                                    </div>
                                    <span className="rounded bg-white px-2 py-1 text-xs font-semibold text-slate-600">
                                        #{account.id}
                                    </span>
                                </div>

                                {account.role === "moderator" && canManageModerators && (
                                    <div className="rounded-lg border border-slate-200 bg-white p-3">
                                        <p className="mb-2 mt-0 text-xs font-semibold uppercase tracking-wide text-slate-500">Moderator permissions</p>
                                        <div className="grid gap-2 sm:grid-cols-2">
                                            {MODERATOR_PERMISSIONS.map((permission) => (
                                                <label key={permission.key} className="flex items-center gap-2 text-sm text-slate-800">
                                                    <input
                                                        type="checkbox"
                                                        checked={Boolean(account.permissions?.[permission.key])}
                                                        onChange={(event) =>
                                                            toggleModeratorPermission(account.id, permission.key, event.target.checked)
                                                        }
                                                    />
                                                    <span>{permission.label}</span>
                                                </label>
                                            ))}
                                        </div>
                                        <button
                                            type="button"
                                            onClick={() => saveModeratorPermissions(account)}
                                            disabled={saveBusyId === account.id}
                                            className="mt-3 rounded-md bg-slate-900 px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-70"
                                        >
                                            {saveBusyId === account.id ? "Saving..." : "Save Permissions"}
                                        </button>
                                    </div>
                                )}

                                {role === "superadmin" && (account.role === "admin" || account.role === "moderator") && (
                                    <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3">
                                        <p className="mb-2 mt-0 text-xs font-semibold uppercase tracking-wide text-slate-500">Set Account Password</p>
                                        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
                                            <input
                                                type="password"
                                                value={passwordResetDrafts[account.id] || ""}
                                                onChange={(event) =>
                                                    setPasswordResetDrafts((current) => ({
                                                        ...current,
                                                        [account.id]: event.target.value,
                                                    }))
                                                }
                                                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                                                minLength={8}
                                                placeholder="New password"
                                            />
                                            <button
                                                type="button"
                                                onClick={() => handleSuperadminPasswordReset(account)}
                                                disabled={passwordResetBusyId === account.id}
                                                className="rounded-md bg-amber-600 px-3 py-2 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-70"
                                            >
                                                {passwordResetBusyId === account.id ? "Updating..." : "Set Password"}
                                            </button>
                                        </div>
                                    </div>
                                )}
                            </li>
                        ))}
                    </ul>
                )}

                {saveMessage && (
                    <p className="mb-0 mt-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-700">
                        {saveMessage}
                    </p>
                )}

                {passwordResetMessage && (
                    <p className="mb-0 mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
                        {passwordResetMessage}
                    </p>
                )}
            </section>
            )}

            {canCreate && (
                <section className="mb-4 rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
                    <h3 className="m-0 text-lg font-semibold text-slate-900">Create Account</h3>
                    <p className="mb-4 mt-1 text-sm text-slate-500">Only superadmin can create admin or moderator accounts.</p>

                    <form className="grid gap-3 sm:grid-cols-2" onSubmit={handleCreateAccount}>
                        <label className="text-sm text-slate-800">
                            <span className="mb-1 block font-semibold">Username</span>
                            <input
                                type="text"
                                value={createUsername}
                                onChange={(event) => setCreateUsername(event.target.value)}
                                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                                required
                            />
                        </label>

                        <label className="text-sm text-slate-800">
                            <span className="mb-1 block font-semibold">Role</span>
                            <select
                                value={createRole}
                                onChange={(event) => setCreateRole(event.target.value as "admin" | "moderator")}
                                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                            >
                                <option value="moderator">Moderator</option>
                                <option value="admin">Admin</option>
                            </select>
                        </label>

                        <label className="text-sm text-slate-800 sm:col-span-2">
                            <span className="mb-1 block font-semibold">Password</span>
                            <input
                                type="password"
                                value={createPassword}
                                onChange={(event) => setCreatePassword(event.target.value)}
                                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm"
                                minLength={8}
                                required
                            />
                        </label>

                        <button
                            type="submit"
                            disabled={createBusy}
                            className="sm:col-span-2 rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-70"
                        >
                            {createBusy ? "Creating..." : "Create Account"}
                        </button>
                    </form>

                    {createMessage && (
                        <p className="mb-0 mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-700">
                            {createMessage}
                        </p>
                    )}
                </section>
            )}
        </>
    );
}

export default Accounts;