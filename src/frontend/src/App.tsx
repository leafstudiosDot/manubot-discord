import { useEffect, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import SideMenu from "./sidemenu";
import Dashboard from "./routes/Dashboard";
import DangerZone from "./routes/DangerZone";
import NotFound from "./routes/NotFound";

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
    const load = async () => {
      try {
        const [healthRes, eventsRes] = await Promise.all([
          fetch("/api/health"),
          fetch("/api/events?limit=20")
        ]);

        const [healthData, eventsData] = await Promise.all([
          healthRes.json(),
          eventsRes.json()
        ]);

        setHealth(healthData);
        setEvents(eventsData);
      } catch (err) {
        console.error("Failed to load dashboard", err);
      } finally {
        setLoading(false);
      }
    };

    load();
    const timer = setInterval(load, 5000);
    return () => clearInterval(timer);
  }, []);

  return (
    <main className="mx-auto max-w-6xl px-4 pb-12 pt-8">
      <header className="mb-6 flex items-center justify-between gap-4">
        <div>
        <h1 className="m-0 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">Manubot Control Panel</h1>
        <p className="mt-2 text-slate-500">v0.0.1</p>
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
            <Route path="/danger-zone" element={<DangerZone />} />
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
