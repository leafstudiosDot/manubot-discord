import { useEffect, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import SideMenu from "./sidemenu";

import Dashboard from "./routes/Dashboard";
import DirectMessages from "./routes/DirectMessages";
import Servers from "./routes/Servers";
import DangerZone from "./routes/DangerZone";
import NotFound from "./routes/NotFound";
import { APP_VERSION } from "./version";

function buildWsUrl(path: string) {
  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  return `${protocol}://${window.location.host}${path}`;
}

function App() {
  const [health, setHealth] = useState(null);
  const [events, setEvents] = useState([]);
  const [loading, setLoading] = useState(true);
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setIsMenuOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    let isCancelled = false;
    let healthWs: WebSocket | null = null;
    let eventsWs: WebSocket | null = null;
    let healthConnected = false;
    let eventsConnected = false;
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
  }, []);

  return (
    <main className="mx-auto max-w-6xl px-4 pb-12 pt-8">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="m-0 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">Manubot Control Panel</h1>
          <p className="mt-2 text-slate-500">{APP_VERSION}</p>
        </div>
        <button
          type="button"
          onClick={() => setIsMenuOpen((value) => !value)}
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white md:hidden"
        >
          {isMenuOpen ? "Close" : "Menu"}
        </button>
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
        <SideMenu isOpen={isMenuOpen} onNavigate={() => setIsMenuOpen(false)} />

        <section className="w-full">
          <Routes>
            <Route
              path="/"
              element={<Dashboard loading={loading} health={health} events={events} />}
            />
            <Route path="/servers" element={<Servers loading={loading} />} />
            <Route path="/danger-zone" element={<DangerZone />} />
            <Route path="/direct-messages" element={<DirectMessages loading={loading} />} />
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
