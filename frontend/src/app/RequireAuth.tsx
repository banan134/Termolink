import { Navigate, useLocation } from "react-router-dom";
import { isOperator } from "@/api/auth";
import { Skeleton } from "@/components/ui";
import { useMe, useThemeSync } from "@/features/auth/useMe";
import { AppLayout } from "./AppLayout";

/** Authenticated shell. Operators without 2FA are sent to /account (docs/08). */
export function RequireAuth() {
  const me = useMe();
  const location = useLocation();
  useThemeSync(me.data);

  if (me.isPending) {
    return (
      <div style={{ padding: 32, maxWidth: 480 }}>
        <Skeleton height={24} />
        <div style={{ height: 12 }} />
        <Skeleton />
      </div>
    );
  }
  if (!me.data) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (isOperator(me.data) && !me.data.totp_enabled && location.pathname !== "/account") {
    return <Navigate to="/account" replace />;
  }
  return <AppLayout me={me.data} />;
}
