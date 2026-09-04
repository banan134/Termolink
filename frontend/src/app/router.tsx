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
const TenantsPage = lazy(() => import("@/features/admin/TenantsPage"));
const TenantDetailPage = lazy(() => import("@/features/admin/TenantDetailPage"));
const TenantUsersPage = lazy(() => import("@/features/admin/TenantUsersPage"));
const DevicesPage = lazy(() => import("@/features/devices/DevicesPage"));
const DevicePage = lazy(() => import("@/features/devices/DevicePage"));
const DeviceSettingsPage = lazy(() => import("@/features/devices/DeviceSettingsPage"));
const ChartExplorerPage = lazy(() => import("@/features/charts/ChartExplorerPage"));
const ReportsPage = lazy(() => import("@/features/reports/ReportsPage"));
const SchedulesPage = lazy(() => import("@/features/reports/SchedulesPage"));
const AlertsPage = lazy(() => import("@/features/alerts/AlertsPage"));
const AlertRulesPage = lazy(() => import("@/features/alerts/AlertRulesPage"));
const ChangesPage = lazy(() => import("@/features/control/ChangesPage"));
const SettingsPage = lazy(() => import("@/features/admin/SettingsPage"));
const LabelsPage = lazy(() => import("@/features/admin/LabelsPage"));

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
          <Route path="/admin/tenants" element={<TenantsPage />} />
          <Route path="/admin/tenants/:id" element={<TenantDetailPage />} />
          <Route path="/t/:tid/users" element={<TenantUsersPage />} />
          <Route path="/t/:tid" element={<DevicesPage />} />
          <Route path="/t/:tid/devices/:id" element={<DevicePage />} />
          <Route path="/t/:tid/devices/:id/settings" element={<DeviceSettingsPage />} />
          <Route path="/t/:tid/devices/:id/chart" element={<ChartExplorerPage />} />
          <Route path="/t/:tid/changes" element={<ChangesPage />} />
          <Route path="/t/:tid/alerts" element={<AlertsPage />} />
          <Route path="/t/:tid/reports" element={<ReportsPage />} />
          <Route path="/t/:tid/reports/schedules" element={<SchedulesPage />} />
          <Route path="/t/:tid/alert-rules" element={<AlertRulesPage />} />
          <Route path="/admin/labels" element={<LabelsPage />} />
          <Route path="/admin/settings" element={<SettingsPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
