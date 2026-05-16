import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';

const navItems = [
  {
    to: '/admin',
    end: true,
    label: 'Dashboard',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0a1 1 0 01-1-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 01-1 1" />
      </svg>
    ),
  },
  {
    to: '/admin/players',
    label: 'Players',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" />
      </svg>
    ),
  },
  {
    to: '/admin/matches',
    label: 'Matches',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
      </svg>
    ),
  },
  {
    to: '/admin/teams',
    label: 'Teams',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5V8l-5-5H7L2 8v12h5m10 0v-6H7v6m10 0H7" />
      </svg>
    ),
  },
  {
    to: '/admin/users',
    label: 'Users',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 20h5v-2a4 4 0 00-3-3.87M9 20H4v-2a4 4 0 013-3.87m9-4a4 4 0 10-8 0 4 4 0 008 0zm6 4a4 4 0 10-8 0 4 4 0 008 0z" />
      </svg>
    ),
  },
  {
    to: '/admin/scores',
    label: 'Score Control',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
      </svg>
    ),
  },
  {
    to: '/admin/missed-players',
    label: 'Missed Players',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h10M4 18h16M18 10l2 2-2 2" />
      </svg>
    ),
  },
  {
    to: '/admin/super-team',
    label: 'Super Team',
    icon: (
      <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 3l2 5 5 2-5 2-2 5-2-5-5-2 5-2 2-5zm14 4l1.5 3 3 1.5-3 1.5-1.5 3-1.5-3-3-1.5 3-1.5L19 7z" />
      </svg>
    ),
  },
];

export default function AdminLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const { profile } = useAuth();

  const linkClasses = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ${
      isActive
        ? 'bg-indigo-600 text-white'
        : 'text-gray-300 hover:bg-gray-700 hover:text-white'
    }`;

  const sidebar = (
    <nav className="flex flex-col gap-1 p-4">
      <div className="flex items-center gap-3 px-4 py-4 mb-4 border-b border-gray-700">
        <div className="w-9 h-9 rounded-full bg-indigo-500 flex items-center justify-center text-white font-bold text-sm">
          {profile?.name?.charAt(0)?.toUpperCase() || 'A'}
        </div>
        <div>
          <p className="text-white text-sm font-semibold">{profile?.name || 'Admin'}</p>
          <p className="text-gray-400 text-xs">Administrator</p>
        </div>
      </div>
      {navItems.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={linkClasses}
          onClick={() => setSidebarOpen(false)}
        >
          {item.icon}
          {item.label}
        </NavLink>
      ))}

      <div className="mt-auto pt-4 border-t border-gray-700 mt-6">
        <NavLink
          to="/dashboard"
          className="flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
          onClick={() => setSidebarOpen(false)}
        >
          <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 17l-5-5m0 0l5-5m-5 5h12" />
          </svg>
          Back to App
        </NavLink>
      </div>
    </nav>
  );

  return (
    <div className="min-h-screen bg-slate-950 flex">
      {/* Desktop sidebar */}
      <aside className="hidden lg:flex lg:flex-col w-64 bg-gray-900 min-h-screen fixed left-0 top-0 z-30">
        {sidebar}
      </aside>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Mobile drawer */}
      <aside
        className={`fixed top-0 left-0 h-full w-64 bg-gray-900 z-50 transform transition-transform duration-300 lg:hidden ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex justify-end p-4">
          <button onClick={() => setSidebarOpen(false)} className="text-gray-400 hover:text-white">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        {sidebar}
      </aside>

      {/* Main content */}
      <div className="flex-1 lg:ml-64 bg-slate-950">
        {/* Mobile header */}
        <header className="lg:hidden bg-slate-900 border-b border-slate-800 px-4 py-3 flex items-center gap-4 sticky top-0 z-20">
          <button onClick={() => setSidebarOpen(true)} className="text-slate-300 hover:text-white">
            <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
            </svg>
          </button>
          <h1 className="text-lg font-semibold text-slate-100">Admin Panel</h1>
        </header>

        <main className="p-6 bg-slate-950 min-h-screen text-slate-900">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
