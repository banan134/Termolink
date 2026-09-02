import type { ReactNode } from "react";
import { Card } from "@/components/ui";
import { t } from "@/i18n/pl";
import s from "./AuthShell.module.css";

/** Frame for unauthenticated screens (login, reset, invitation). Always light theme. */
export function AuthShell({
  title,
  help,
  children,
}: {
  title: string;
  help?: string;
  children: ReactNode;
}) {
  return (
    <div className={s.page}>
      <header className={s.header}>{t.app}</header>
      <div className={s.center}>
        <div className={s.box}>
          <Card>
            <h1 className={s.title}>{title}</h1>
            {help && <p className={s.help}>{help}</p>}
            {children}
          </Card>
          <p className={s.footer}>Termolink · Wodmiar</p>
        </div>
      </div>
    </div>
  );
}
