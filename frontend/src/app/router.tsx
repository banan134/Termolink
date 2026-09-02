import { lazy, Suspense } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { Skeleton } from "@/components/ui";
import { RequireAuth } from "./RequireAuth";

// Code-splitting per screen (docs/09 §Wydajność).
const HomePage = lazy(() => import("@/features/home/HomePage"));
const LoginPage = lazy(() => import("@/features/auth/LoginPage"));
const ResetPage = lazy(() => import("@/features/auth/ResetPage"));
const InvitePage = lazy(() => import("@/features/auth/InvitePage"));
const AccountPage = lazy(() => import("@/features/account/AccountPage"));

function Fallback() {
  return (
    <div style={{ padding: 32, maxWidth: 480 }}>
      <Skeleton height={24} />
    </div>
  );
}

export function AppRoutes() {
  return (
    <Suspense fallback={<Fallback />}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/reset" element={<ResetPage />} />
        <Route path="/invite/:token" element={<InvitePage />} />
        <Route element={<RequireAuth />}>
          <Route index element={<HomePage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
