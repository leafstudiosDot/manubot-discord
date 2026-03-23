import { useEffect, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import SideMenu from "./sidemenu";

import Dashboard from "./routes/Dashboard";
import DirectMessages from "./routes/DirectMessages";
import Servers from "./routes/Servers";
import Accounts from "./routes/Accounts";
import DangerZone from "./routes/DangerZone";
import NotFound from "./routes/NotFound";
import { APP_VERSION } from "./version";

type PermissionMap = Record<string, boolean>;

type AuthSession = {
  username: string;
  role: "superadmin" | "admin" | "moderator";
  permissions: PermissionMap;
  expires_at: string;
};

function buildWsUrl(path: string) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}${path}`;
}

function App() {
  const [health, setHealth] = useState(null);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [authLoading, setAuthLoading] = useState(true);
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginBusy, setLoginBusy] = useState(false);
  const [loginError, setLoginError] = useState<string | null>(null);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const location = useLocation();

  const hasPermission = (permission: string) => {
    if (!session) {
      return false;
    }
    if (session.role === "superadmin" || session.role === "admin") {
      return true;
    }
    return Boolean(session.permissions?.[permission]);
  };

  useEffect(() => {
    let cancelled = false;

    const loadSession = async () => {
      try {
        const response = await fetch("/api/auth/session");
        if (!response.ok) {
          throw new Error("Not authenticated");
        }
        const data = await response.json();
        if (!cancelled) {
          setSession(data?.session || null);
          setLoginError(null);
        }
      } catch {
        if (!cancelled) {
          setSession(null);
        }
      } finally {
        if (!cancelled) {
          setAuthLoading(false);
        }
      }
    };

    loadSession();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setLoginBusy(true);
    setLoginError(null);

    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          username: loginUsername,
          password: loginPassword,
        }),
      });

      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.message || "Login failed");
      }

      setSession(data?.session || null);
      setLoginPassword("");
    } catch (err) {
      setLoginError(err instanceof Error ? err.message : "Login failed");
      setSession(null);
    } finally {
      setLoginBusy(false);
    }
  };

  const handleLogout = async () => {
    try {
      await fetch("/api/auth/logout", { method: "POST" });
    } catch (err) {
      console.error("Logout failed", err);
    } finally {
      setSession(null);
      setEvents([]);
      setHealth(null);
    }
  };

  const handleSessionRevoked = () => {
    setSession(null);
    setEvents([]);
    setHealth(null);
  };

  useEffect(() => {
    setIsMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!session) {
      setLoading(false);
      return;
    }

    let isCancelled = false;
    let healthWs: WebSocket | null = null;
    let eventsWs: WebSocket | null = null;
    let healthConnected = false;
    let eventsConnected = !hasPermission("events_view");
    let healthReconnect: number | null = null;
    let eventsReconnect: number | null = null;

    const setReady = () => {
      if (healthConnected && eventsConnected && !isCancelled) {
        setLoading(false);
      }
    };

    const connectHealth = () => {
      healthWs = new WebSocket(buildWsUrl("/ws/health"));

      healthWs.onopen = () => {
        healthConnected = true;
        setReady();
      };

      healthWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setHealth(data);
          setLoading(false);
        } catch (err) {
          console.error("Invalid health websocket payload", err);
        }
      };

      healthWs.onerror = (err) => {
        console.error("Health websocket error", err);
      };

      healthWs.onclose = () => {
        healthConnected = false;
        if (!isCancelled) {
          healthReconnect = window.setTimeout(connectHealth, 1500);
        }
      };
    };

    const connectEvents = () => {
      if (!hasPermission("events_view")) {
        setEvents([]);
        setReady();
        return;
      }

      eventsWs = new WebSocket(buildWsUrl("/ws/events?limit=20"));

      eventsWs.onopen = () => {
        eventsConnected = true;
        setReady();
      };

      eventsWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          setEvents(Array.isArray(data) ? data : []);
          setLoading(false);
        } catch (err) {
          console.error("Invalid events websocket payload", err);
        }
      };

      eventsWs.onerror = (err) => {
        console.error("Events websocket error", err);
      };

      eventsWs.onclose = () => {
        eventsConnected = false;
        if (!isCancelled) {
          eventsReconnect = window.setTimeout(connectEvents, 1500);
        }
      };
    };

    connectHealth();
    connectEvents();

    return () => {
      isCancelled = true;

      if (healthReconnect !== null) {
        window.clearTimeout(healthReconnect);
      }

      if (eventsReconnect !== null) {
        window.clearTimeout(eventsReconnect);
      }

      if (healthWs) {
        healthWs.close();
      }

      if (eventsWs) {
        eventsWs.close();
      }
    };
  }, [session]);

  if (authLoading) {
    return (
      <main className="mx-auto max-w-md px-4 pb-12 pt-12">
        <section className="rounded-2xl bg-white p-5 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
          <h1 className="m-0 text-2xl font-bold text-slate-900">Manubot Control Panel</h1>
          <p className="mb-0 mt-2 text-slate-600">Checking session...</p>
        </section>
      </main>
    );
  }

  if (!session) {
    return (
      <main className="mx-auto max-w-md px-4 pb-12 pt-12">
        <section className="rounded-2xl bg-white p-6 shadow-[0_8px_28px_rgba(15,28,45,0.08)]">
          <h1 className="m-0 text-2xl font-bold tracking-tight text-slate-900">Manubot Control Panel</h1>
          <p className="mb-5 mt-2 text-sm text-slate-500">Sign in to continue.</p>

          <form className="space-y-3" onSubmit={handleLogin}>
            <div>
              <label htmlFor="username" className="mb-1 block text-sm font-semibold text-slate-800">
                Username
              </label>
              <input
                id="username"
                type="text"
                value={loginUsername}
                onChange={(event) => setLoginUsername(event.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-slate-400 focus:border-slate-400 focus:ring-2"
                autoComplete="username"
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="mb-1 block text-sm font-semibold text-slate-800">
                Password
              </label>
              <input
                id="password"
                type="password"
                value={loginPassword}
                onChange={(event) => setLoginPassword(event.target.value)}
                className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 outline-none ring-slate-400 focus:border-slate-400 focus:ring-2"
                autoComplete="current-password"
                required
              />
            </div>

            {loginError && (
              <p className="m-0 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {loginError}
              </p>
            )}

            <button
              type="submit"
              disabled={loginBusy}
              className="w-full rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-70"
            >
              {loginBusy ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </section>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-6xl px-4 pb-12 pt-8">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="m-0 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">Manubot Control Panel</h1>
          <p className="mt-2 text-slate-500">
            {APP_VERSION} • Signed in as <span className="font-semibold text-slate-700">{session.username}</span> ({session.role})
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleLogout}
            className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100"
          >
            Logout
          </button>
          <button
            type="button"
            onClick={() => setIsMenuOpen((value) => !value)}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white md:hidden"
          >
            {isMenuOpen ? "Close" : "Menu"}
          </button>
        </div>
      </header>

      {isMenuOpen && (
        <button
          type="button"
          aria-label="Close menu overlay"
          onClick={() => setIsMenuOpen(false)}
          className="fixed inset-0 z-30 bg-black/30 md:hidden"
        />
      )}

      <div className="relative flex gap-4 lg:gap-6">
        <SideMenu
          isOpen={isMenuOpen}
          onNavigate={() => setIsMenuOpen(false)}
          canViewDirectMessages={hasPermission("direct_messages_read")}
          canViewServers={hasPermission("servers_view")}
          canViewAccounts={true}
          canViewDangerZone={true}
        />

        <section className="w-full">
          <Routes>
            <Route
              path="/"
              element={<Dashboard loading={loading} health={health} events={events} />}
            />
            <Route
              path="/servers"
              element={<Servers loading={loading} canView={hasPermission("servers_view")} />}
            />
            <Route
              path="/danger-zone"
              element={
                <DangerZone
                  canRegenerate={session.role === "superadmin"}
                  canRevokeAll={true}
                  canRevokeAllGlobal={session.role === "superadmin"}
                  onSessionRevoked={handleSessionRevoked}
                />
              }
            />
            <Route
              path="/direct-messages"
              element={
                <DirectMessages
                  loading={loading}
                  canRead={hasPermission("direct_messages_read")}
                  canSend={hasPermission("direct_messages_send")}
                  canDelete={hasPermission("direct_messages_delete")}
                />
              }
            />
            <Route
              path="/accounts"
              element={
                <Accounts
                  canView={hasPermission("accounts_view")}
                  role={session.role}
                  username={session.username}
                  canCreate={session.role === "superadmin"}
                  canManageModerators={session.role === "superadmin" || session.role === "admin"}
                />
              }
            />
            <Route path="*" element={<NotFound />} />
          </Routes>

          <footer className="pt-2 text-center text-sm text-slate-500">
            <p className="m-0">© {new Date().getFullYear()} leafstudiosDot</p>
          </footer>
        </section>
      </div>
    </main>
  );
}

export default App;
