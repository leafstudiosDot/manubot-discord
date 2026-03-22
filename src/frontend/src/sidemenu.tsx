import { NavLink } from "react-router-dom";

type SideMenuProps = {
  isOpen: boolean;
  onNavigate: () => void;
};

function SideMenu({ isOpen, onNavigate }: SideMenuProps) {
  const navItemBase =
    "block w-full rounded-xl px-3 py-2 text-left text-sm font-medium transition-colors";
  const wrapperClass = isOpen
    ? "fixed inset-y-0 left-0 z-40 block w-72"
    : "hidden";

  return (
    <aside className={`${wrapperClass} md:static md:block md:w-64 md:shrink-0`}>
      <div className="h-full rounded-none bg-gray-50 p-4 text-slate-100 shadow-xl md:h-fit md:rounded-2xl">
        <p className="mb-4 text-xs text-slate-400">Discord Bot</p>
        <nav className="space-y-2">
          <NavLink
            to="/"
            onClick={onNavigate}
            end
            className={({ isActive }) =>
              `${navItemBase} ${isActive
                ? "bg-gray-600 text-white"
                : "bg-gray-500 text-white hover:bg-gray-600"
              }`
            }
          >
            Dashboard
          </NavLink>
          <NavLink
            to="/direct-messages"
            onClick={onNavigate}
            end
            className={({ isActive }) =>
              `${navItemBase} ${isActive
                ? "bg-gray-600 text-white"
                : "bg-gray-500 text-white hover:bg-gray-600"
              }`
            }
          >
            Direct Messages
          </NavLink>
          <NavLink
            to="/servers"
            onClick={onNavigate}
            end
            className={({ isActive }) =>
              `${navItemBase} ${isActive
                ? "bg-gray-600 text-white"
                : "bg-gray-500 text-white hover:bg-gray-600"
              }`
            }
          >
            Servers
          </NavLink>
          <NavLink
            to="/danger-zone"
            onClick={onNavigate}
            className={({ isActive }) =>
              `${navItemBase} ${isActive
                ? "bg-rose-700"
                : "bg-rose-500 text-white hover:bg-rose-700"
              }`
            }
          >
            Danger Zone
          </NavLink>
        </nav>
        <p className="mt-4 text-xs text-slate-400">
          Powered by Manubot v0.0.1
        </p>
      </div>
    </aside>
  );
}

export default SideMenu;
