import { NavLink, Navigate, Route, Routes } from "react-router";
import { Header } from "@/components/layout/header";
import { useAuth } from "@/hooks/use-auth";
import { CapacityPage } from "./capacity-page";
import { navFor } from "./nav";
import { NoAccess } from "./no-access";
import { SessionsPage } from "./sessions-page";

const Soon = ({ name }: { name: string }) => <p className="text-sm text-muted-foreground">{name} is coming soon.</p>;

/** /admin shell: left nav gated by staff role; the API stays the real gate (403 -> No access). */
export function AdminConsole() {
  const { user } = useAuth();
  const items = navFor(user?.staff_role);
  return (
    <div className="flex h-dvh flex-col bg-background styx-app-bg">
      <Header activeTab="home" onTabChange={() => { window.location.assign("/"); }} />
      <div className="flex min-h-0 flex-1 max-md:flex-col">
        {items.length > 0 && (
          <nav aria-label="Admin console" className="flex shrink-0 gap-1 border-b border-border p-3 max-md:overflow-x-auto md:w-52 md:flex-col md:border-b-0 md:border-r">
            {items.map((n) => (
              <NavLink key={n.to} to={`/admin/${n.to}`}
                className={({ isActive }) => `rounded-md px-3 py-2 text-sm max-md:min-h-11 ${isActive ? "bg-secondary font-medium" : "text-muted-foreground hover:bg-secondary"}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
        )}
        <main className="min-w-0 flex-1 overflow-y-auto p-6">
          {items.length === 0 ? <NoAccess /> : (
            <Routes>
              <Route index element={<Navigate to="sessions" replace />} />
              <Route path="sessions" element={<SessionsPage />} />
              <Route path="capacity" element={<CapacityPage />} />
              {items.filter((n) => !["sessions", "capacity"].includes(n.to)).map((n) => (
                <Route key={n.to} path={n.to} element={<Soon name={n.label} />} />
              ))}
              <Route path="*" element={<Navigate to="sessions" replace />} />
            </Routes>
          )}
        </main>
      </div>
    </div>
  );
}
