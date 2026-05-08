import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import {
  LayoutDashboard, MessageSquare, BookOpen, FileText, Users,
  Database, GraduationCap, LogOut, Menu, X, Bell, ChevronRight,
  ClipboardList, Settings
} from 'lucide-react';

const SCHOOL_NAME = import.meta.env.VITE_SCHOOL_NAME || 'School AI Platform';

const navConfig = {
  student: [
    { path: '/student/dashboard', icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/student/chat',      icon: MessageSquare,    label: 'AI Chatbot' },
    { path: '/student/assignments', icon: BookOpen,       label: 'Assignments' },
  ],
  teacher: [
    { path: '/teacher/dashboard',          icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/teacher/chat',               icon: MessageSquare,   label: 'AI Assistant' },
    { path: '/teacher/assignments/create', icon: ClipboardList,   label: 'Create Assignment' },
    { path: '/teacher/question-papers',    icon: FileText,        label: 'Question Papers' },
  ],
  admin: [
    { path: '/admin/dashboard',     icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/admin/users',         icon: Users,           label: 'Manage Users' },
    { path: '/admin/knowledge-base',icon: Database,        label: 'Knowledge Base' },
  ],
};

const roleColors = {
  student: 'from-blue-700 to-blue-900',
  teacher: 'from-emerald-700 to-emerald-900',
  admin:   'from-purple-700 to-purple-900',
};
const roleBadgeColors = {
  student: 'bg-blue-500/20 text-blue-100',
  teacher: 'bg-emerald-500/20 text-emerald-100',
  admin:   'bg-purple-500/20 text-purple-100',
};

export default function Layout({ children, title }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const navItems = navConfig[user?.role] || [];
  const gradient = roleColors[user?.role] || 'from-blue-700 to-blue-900';
  const badgeColor = roleBadgeColors[user?.role] || 'bg-blue-500/20 text-blue-100';

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const SidebarContent = () => (
    <div className={`h-full flex flex-col bg-gradient-to-b ${gradient} text-white`}>
      {/* Logo */}
      <div className="p-5 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg overflow-hidden flex items-center justify-center bg-white">
            <img src="/logo.jpeg" alt="LSS Logo" className="w-full h-full object-contain" style={{mixBlendMode:'multiply'}} />
          </div>
          <div>
            <div className="font-bold text-sm leading-tight">{SCHOOL_NAME}</div>
            <div className="text-white/60 text-xs">AI Learning Platform</div>
          </div>
        </div>
      </div>

      {/* User Info */}
      <div className="p-4 border-b border-white/10">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-white/20 rounded-full flex items-center justify-center text-base font-bold">
            {user?.name?.charAt(0)?.toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-sm truncate">{user?.name}</div>
            <div className="flex items-center gap-1 mt-0.5">
              <span className={`text-xs px-2 py-0.5 rounded-full ${badgeColor} capitalize`}>
                {user?.role}
              </span>
              {user?.class_name && (
                <span className="text-xs text-white/60">{user.class_name}</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 overflow-y-auto">
        <div className="space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                onClick={() => setSidebarOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all
                  ${active
                    ? 'bg-white/20 font-semibold text-white'
                    : 'text-white/70 hover:bg-white/10 hover:text-white'
                  }`}
              >
                <Icon size={18} />
                <span>{item.label}</span>
                {active && <ChevronRight size={14} className="ml-auto" />}
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-white/10">
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm
                     text-white/70 hover:bg-white/10 hover:text-white transition-all"
        >
          <LogOut size={18} />
          <span>Sign Out</span>
        </button>
      </div>
    </div>
  );

  return (
    <div className="min-h-screen flex bg-gray-50">
      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex flex-col w-64 shrink-0 h-screen sticky top-0">
        <SidebarContent />
      </aside>

      {/* Mobile Overlay */}
      {sidebarOpen && (
        <div className="lg:hidden fixed inset-0 z-40">
          <div className="absolute inset-0 bg-black/50" onClick={() => setSidebarOpen(false)} />
          <aside className="absolute left-0 top-0 bottom-0 w-64">
            <SidebarContent />
          </aside>
        </div>
      )}

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Bar */}
        <header className="sticky top-0 z-30 bg-white border-b border-gray-200 px-4 lg:px-6 py-3 flex items-center gap-3">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden p-2 rounded-lg hover:bg-gray-100"
          >
            <Menu size={20} />
          </button>
          <h1 className="font-semibold text-gray-800 flex-1 text-base lg:text-lg truncate">
            {title}
          </h1>
          <div className="flex items-center gap-2">
            <span className="hidden sm:block text-sm text-gray-500">{user?.name}</span>
            <div className="w-8 h-8 bg-blue-100 rounded-full flex items-center justify-center text-blue-700 text-sm font-bold">
              {user?.name?.charAt(0)?.toUpperCase()}
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 p-4 lg:p-6 overflow-auto">
          {children}
        </main>
      </div>
    </div>
  );
}
