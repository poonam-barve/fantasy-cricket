import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext';
import { ProtectedRoute, AdminRoute } from './auth/ProtectedRoute';
import Navbar from './components/Navbar';
import { ToastProvider } from './components/Toast';
import { lazy, Suspense } from 'react';
import LoadingSpinner from './components/LoadingSpinner';

const Login = lazy(() => import('./pages/Login'));
const Register = lazy(() => import('./pages/Register'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const SelectTeam = lazy(() => import('./pages/SelectTeam'));
const ViewScores = lazy(() => import('./pages/ViewScores'));
const Leaderboard = lazy(() => import('./pages/Leaderboard'));
const PointsTable = lazy(() => import('./pages/PointsTable'));
const Rules = lazy(() => import('./pages/Rules'));
const Settings = lazy(() => import('./pages/Settings'));
const WeekendTournament = lazy(() => import('./pages/WeekendTournament'));

const AdminLayout = lazy(() => import('./pages/admin/AdminLayout'));
const AdminDashboard = lazy(() => import('./pages/admin/AdminDashboard'));
const ManagePlayers = lazy(() => import('./pages/admin/ManagePlayers'));
const ManageMatches = lazy(() => import('./pages/admin/ManageMatches'));
const ManageUsers = lazy(() => import('./pages/admin/ManageUsers'));
const ScoreControl = lazy(() => import('./pages/admin/ScoreControl'));
const ManageTeams = lazy(() => import('./pages/admin/ManageTeams'));
const MissedPlayers = lazy(() => import('./pages/admin/MissedPlayers'));

function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[#0a0a0a]"
      style={{
        backgroundImage: `
          radial-gradient(ellipse at 50% 0%, rgba(34,197,94,0.06) 0%, transparent 60%),
          radial-gradient(ellipse at 50% 100%, rgba(34,197,94,0.03) 0%, transparent 50%),
          repeating-linear-gradient(0deg, transparent, transparent 80px, rgba(255,255,255,0.015) 80px, rgba(255,255,255,0.015) 81px)
        `
      }}>
      <Navbar />
      <main className="max-w-6xl mx-auto px-4 py-6">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
        <Suspense fallback={<LoadingSpinner />}>
          <Routes>
            {/* Public */}
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />

            {/* Protected user routes */}
            <Route path="/dashboard" element={<ProtectedRoute><AppLayout><Dashboard /></AppLayout></ProtectedRoute>} />
            <Route path="/select-team/:matchId" element={<ProtectedRoute><AppLayout><SelectTeam /></AppLayout></ProtectedRoute>} />
            <Route path="/view-scores/:matchId" element={<ProtectedRoute><AppLayout><ViewScores /></AppLayout></ProtectedRoute>} />
            <Route path="/leaderboard" element={<ProtectedRoute><AppLayout><Leaderboard /></AppLayout></ProtectedRoute>} />
            <Route path="/points-table" element={<ProtectedRoute><AppLayout><PointsTable /></AppLayout></ProtectedRoute>} />
            <Route path="/weekend" element={<ProtectedRoute><AppLayout><WeekendTournament /></AppLayout></ProtectedRoute>} />
            <Route path="/rules" element={<ProtectedRoute><AppLayout><Rules /></AppLayout></ProtectedRoute>} />
            <Route path="/settings" element={<ProtectedRoute><AppLayout><Settings /></AppLayout></ProtectedRoute>} />

            {/* Admin routes with nested layout */}
            <Route path="/admin" element={<AdminRoute><AdminLayout /></AdminRoute>}>
              <Route index element={<AdminDashboard />} />
              <Route path="players" element={<ManagePlayers />} />
              <Route path="matches" element={<ManageMatches />} />
              <Route path="teams" element={<ManageTeams />} />
              <Route path="users" element={<ManageUsers />} />
              <Route path="scores" element={<ScoreControl />} />
              <Route path="missed-players" element={<MissedPlayers />} />
            </Route>

            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Suspense>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
