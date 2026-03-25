import { useState } from "react";
import Prompt from "../components/prompt";

type DangerZoneProps = {
  canRegenerate: boolean;
  canRevokeAll: boolean;
  canRevokeAllGlobal: boolean;
  onSessionRevoked: () => void;
};

function DangerZone({ canRegenerate, canRevokeAll, canRevokeAllGlobal, onSessionRevoked }: DangerZoneProps) {
  const [openPrompt, setOpenPrompt] = useState(false);
  const [openRevokePrompt, setOpenRevokePrompt] = useState(false);
  const [openGlobalRevokePrompt, setOpenGlobalRevokePrompt] = useState(false);
  const [working, setWorking] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [revokingGlobal, setRevokingGlobal] = useState(false);
  const [result, setResult] = useState("");
  const [revokeResult, setRevokeResult] = useState("");
  const [globalRevokeResult, setGlobalRevokeResult] = useState("");

  const handleRegenerate = async () => {
    setWorking(true);
    setResult("");
    try {
      const response = await fetch("/api/database/regenerate", { method: "DELETE" });
      const data = await response.json();

      if (!response.ok) {
        throw new Error(data?.message || "Failed to regenerate database.");
      }

      setResult(`Success: ${data.deleted_count} rows deleted. Restarting backend...`);
      setOpenPrompt(false);
    } catch (err) {
      setResult(`Error: ${err.message}`);
    } finally {
      setWorking(false);
    }
  };

  const handleRevokeAllSessions = async () => {
    setRevoking(true);
    setRevokeResult("");
    try {
      const response = await fetch("/api/sessions/revoke-all", { method: "POST" });
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data?.message || "Failed to revoke sessions.");
      }

      setOpenRevokePrompt(false);
      setRevokeResult(`Success: ${data?.revoked_count || 0} session(s) for this account revoked.`);
      onSessionRevoked();
    } catch (err) {
      setRevokeResult(`Error: ${err instanceof Error ? err.message : "Failed to revoke sessions."}`);
    } finally {
      setRevoking(false);
    }
  };

  const handleRevokeAllGlobalSessions = async () => {
    setRevokingGlobal(true);
    setGlobalRevokeResult("");
    try {
      const response = await fetch("/api/sessions/revoke-all-global", { method: "POST" });
      const data = await response.json().catch(() => ({}));

      if (!response.ok) {
        throw new Error(data?.message || "Failed to revoke all sessions.");
      }

      setOpenGlobalRevokePrompt(false);
      setGlobalRevokeResult(`Success: ${data?.revoked_count || 0} session(s) revoked globally.`);
      onSessionRevoked();
    } catch (err) {
      setGlobalRevokeResult(`Error: ${err instanceof Error ? err.message : "Failed to revoke all sessions."}`);
    } finally {
      setRevokingGlobal(false);
    }
  };

  return (
    <>
      <section className="mb-4 rounded-2xl border border-rose-200 bg-rose-50 p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
        <h2 className="mt-0 text-xl font-semibold text-rose-700">Danger Zone</h2>
        <p className="mb-4 text-sm text-rose-700">
          Warning: This section contains actions that may have irreversible consequences. Proceed with caution and ensure you understand the implications of any action taken here.
        </p>

        {canRegenerate && (
          <div className="rounded-xl border border-rose-300 bg-white p-4">
            <h3 className="m-0 text-base font-semibold text-slate-900">Regenerate manubot.db</h3>
            <p className="mb-4 mt-2 text-sm text-slate-700">
              This will delete all stored gateway events from the SQLite database.
            </p>
            <button
              type="button"
              onClick={() => setOpenPrompt(true)}
              className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white hover:bg-rose-700"
            >
              Regenerate Database
            </button>
            {result && <p className="mt-3 text-sm text-slate-700">{result}</p>}
          </div>
        )}

        <div className="mt-4 rounded-xl border border-amber-300 bg-white p-4">
          <h3 className="m-0 text-base font-semibold text-slate-900">Revoke My Sessions</h3>
          <p className="mb-4 mt-2 text-sm text-slate-700">
            This revokes all active sessions of your own account across devices and forces a fresh login.
          </p>
          <button
            type="button"
            onClick={() => setOpenRevokePrompt(true)}
            disabled={!canRevokeAll}
            className="rounded-lg bg-amber-600 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-700 disabled:cursor-not-allowed disabled:bg-amber-300"
          >
            Revoke My Sessions
          </button>
          {!canRevokeAll && (
            <p className="mt-3 text-sm text-amber-700">This action is unavailable for your current role.</p>
          )}
          {revokeResult && <p className="mt-3 text-sm text-slate-700">{revokeResult}</p>}
        </div>

        {canRevokeAllGlobal && (
          <div className="mt-4 rounded-xl border border-red-300 bg-white p-4">
            <h3 className="m-0 text-base font-semibold text-slate-900">Revoke All Sessions (Global)</h3>
            <p className="mb-4 mt-2 text-sm text-slate-700">
              Superadmin only: revoke all active sessions for Superadmin, Admin, and Moderator accounts.
            </p>
            <button
              type="button"
              onClick={() => setOpenGlobalRevokePrompt(true)}
              disabled={!canRevokeAllGlobal}
              className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:bg-red-300"
            >
              Revoke All Global Sessions
            </button>
            {globalRevokeResult && <p className="mt-3 text-sm text-slate-700">{globalRevokeResult}</p>}
          </div>
        )}
      </section>

      <Prompt
        open={openPrompt}
        title="Confirm Database Regeneration"
        message="This action will remove all saved gateway event records from manubot.db. Do you want to continue?"
        confirmText="Yes, regenerate"
        cancelText="Cancel"
        danger
        busy={working}
        onCancel={() => setOpenPrompt(false)}
        onConfirm={handleRegenerate}
      />

      <Prompt
        open={openRevokePrompt}
        title="Confirm Session Revoke"
        message="This will revoke all sessions of your account across devices immediately. Continue?"
        confirmText="Yes, revoke my sessions"
        cancelText="Cancel"
        danger
        busy={revoking}
        onCancel={() => setOpenRevokePrompt(false)}
        onConfirm={handleRevokeAllSessions}
      />

      <Prompt
        open={openGlobalRevokePrompt}
        title="Confirm Global Session Revoke"
        message="This will revoke all active sessions for Superadmin, Admin, and Moderator accounts. Continue?"
        confirmText="Yes, revoke all globally"
        cancelText="Cancel"
        danger
        busy={revokingGlobal}
        onCancel={() => setOpenGlobalRevokePrompt(false)}
        onConfirm={handleRevokeAllGlobalSessions}
      />
    </>
  );
}

export default DangerZone;
