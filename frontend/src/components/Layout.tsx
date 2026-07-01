import { NavLink, Outlet } from "react-router-dom";

const links = [
  { to: "/", label: "Feed" },
  { to: "/search", label: "Search" },
  { to: "/analytics", label: "Analytics" },
  { to: "/settings", label: "Settings" },
];

export default function Layout() {
  return (
    <div className="min-h-screen flex">
      <aside className="w-56 bg-slate-900 border-r border-slate-800 p-4 flex flex-col gap-2">
        <h1 className="text-lg font-semibold mb-4 text-emerald-400">Verdi Monitor</h1>
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.to === "/"}
            className={({ isActive }) =>
              `px-3 py-2 rounded-lg text-sm ${
                isActive ? "bg-emerald-600 text-white" : "text-slate-300 hover:bg-slate-800"
              }`
            }
          >
            {l.label}
          </NavLink>
        ))}
      </aside>
      <main className="flex-1 p-6 overflow-auto">
        <Outlet />
      </main>
    </div>
  );
}
