import { useState } from "react";
import Prompt from "../components/prompt";

function DangerZone() {
  const [openPrompt, setOpenPrompt] = useState(false);
  const [working, setWorking] = useState(false);
  const [result, setResult] = useState("");

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

  return (
    <>
      <section className="mb-4 rounded-2xl border border-rose-200 bg-rose-50 p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
        <h2 className="mt-0 text-xl font-semibold text-rose-700">Danger Zone</h2>
        <p className="mb-4 text-sm text-rose-700">
          Warning: This section contains actions that may have irreversible consequences. Proceed with caution and ensure you understand the implications of any action taken here.
        </p>

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
    </>
  );
}

export default DangerZone;
