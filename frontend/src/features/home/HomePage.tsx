import { Navigate } from "react-router-dom";
import { useMe } from "@/features/auth/useMe";
import { OperatorDashboard } from "./OperatorDashboard";

export default function HomePage() {
  const me = useMe();
  if (!me.data) return null;
  if (me.data.tenant) return <Navigate to={`/t/${me.data.tenant.id}`} replace />;
  return <OperatorDashboard />;
}
