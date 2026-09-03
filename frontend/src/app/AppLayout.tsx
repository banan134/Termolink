import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { isOperator, type Me } from "@/api/auth";
import { t } from "@/i18n/pl";
import { useLogout, useSetTheme } from "@/features/auth/useMe";
import s from "./AppLayout.module.css";

function Nav({ me }: { me: Me }) {
  const link = ({ isActive }: { isActive: boolean }) =>
    `${s.navLink} ${isActive ? s.navActive : ""}`;
  return (
    <nav className={s.nav} aria-label="Nawigacja">
      <NavLink to="/" end className={link}>
        {t.nav.dashboard}
      </NavLink>
      {isOperator(me) && (
        <>
          <div className={s.navGroup}>Operator</div>
          <NavLink to="/admin/tenants" className={link}>
            {t.nav.tenants}
          </NavLink>
          {me.role === "superadmin" && (
            <NavLink to="/admin/labels" className={link}>
              {t.nav.labels}
            </NavLink>
          )}
        </>
      )}
      {me.role === "tenant_admin" && me.tenant && (
        <NavLink to={`/t/${me.tenant.id}/users`} className={link}>
          {t.nav.users}
        </NavLink>
      )}
      <div className={s.navGroup}>{t.nav.account}</div>
      <NavLink to="/account" className={link}>
        {t.nav.account}
      </NavLink>
    </nav>
  );
}

export function AppLayout({ me }: { me: Me }) {
  const navigate = useNavigate();
  const setTheme = useSetTheme();
  const logout = useLogout();
  const dark = me.ui_theme === "dark";

  return (
    <div className={s.shell}>
      <NavLink to="/" className={s.brand}>
        {t.app}
      </NavLink>
      <header className={s.top}>
        {isOperator(me) && me.tenant && (
          <span className={s.banner}>{t.nav.operatorBanner(me.tenant.name)}</span>
        )}
        <div className={s.topRight}>
          <span className={s.who}>
            {me.email} · {t.roles[me.role]}
          </span>
          <button
            type="button"
            className={s.iconButton}
            onClick={() => setTheme.mutate(dark ? "light" : "dark")}
            aria-pressed={dark}
          >
            {dark ? t.nav.themeLight : t.nav.themeDark}
          </button>
          <button
            type="button"
            className={s.iconButton}
            onClick={() => logout.mutate(undefined, { onSettled: () => navigate("/login") })}
          >
            {t.nav.logout}
          </button>
        </div>
      </header>
      <Nav me={me} />
      <main className={s.main}>
        <Outlet />
      </main>
    </div>
  );
}

export function PageTitle({ children }: { children: string }) {
  return <h1 className={s.pageTitle}>{children}</h1>;
}
