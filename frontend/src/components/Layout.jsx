import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { useAuth } from '../context/AuthContext';
import { erpAPI } from '../services/api';
import AuroraBackground from './AuroraBackground';
import ThemeToggle from './ThemeToggle';
import {
  LayoutDashboard, MessageSquare, BookOpen, FileText, Users,
  Database, LogOut, Menu, X, ClipboardList, Sparkles, GraduationCap, FileSpreadsheet,
  CalendarRange, ClipboardCheck, Video, Radio, PlaySquare,
  Building2, ShieldCheck, Settings, Wallet, UserPlus, Home,
  Banknote, Coins, AlertCircle, Scale, PenLine, Trophy,
} from 'lucide-react';

const SCHOOL_NAME = import.meta.env.VITE_SCHOOL_NAME || 'School AI Platform';

const navConfig = {
  student: [
    { path: '/student/dashboard',      icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/student/online-classes', icon: Video,           label: "Today's Classes" },
    { path: '/student/chat',           icon: MessageSquare,   label: 'AI Chatbot' },
    { path: '/student/assignments',    icon: BookOpen,        label: 'Assignments' },
    { path: '/student/recorded-classes', icon: PlaySquare,   label: 'Recorded Classes' },
    { path: '/student/question-papers', icon: FileText,       label: 'Question Papers' },
    { path: '/student/practice',       icon: ClipboardList,   label: 'Practice & Self-Test' },
  ],
  teacher: [
    { path: '/teacher/dashboard',          icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/teacher/online-classes',     icon: Video,           label: 'Online Classes' },
    { path: '/teacher/chat',               icon: MessageSquare,   label: 'AI Assistant' },
    { path: '/teacher/assignments/create', icon: ClipboardList,   label: 'Create Assignment' },
    { path: '/teacher/assignments',        icon: BookOpen,        label: 'Review & Grade' },
    { path: '/teacher/question-papers',    icon: FileText,        label: 'Question Papers' },
    { path: '/teacher/lesson-plans',       icon: CalendarRange,   label: 'Lesson Plans' },
  ],
  admin: [
    { path: '/admin/dashboard',     icon: LayoutDashboard, label: 'Dashboard' },
    { path: '/admin/live-classes',  icon: Radio,           label: 'Live Classes' },
    { path: '/admin/users',         icon: Users,           label: 'Manage Users' },
    { path: '/admin/import-students', icon: FileSpreadsheet, label: 'Bulk Import' },
    { path: '/admin/knowledge-base',icon: Database,        label: 'Knowledge Base' },
    { path: '/admin/content',       icon: ClipboardCheck,  label: 'Content Oversight' },
    { path: '/admin/academic-settings', icon: GraduationCap, label: 'Academic Settings' },
  ],
};

// The ERP's own navigation.
//
// Appended to whatever the user's role already shows rather than replacing it,
// so nobody loses a link they use today — and filtered by what the server says
// this person may actually do. A teacher sees Attendance and nothing else; the
// accountant never sees a link that would only 403 at them.
const erpNav = [
  { path: '/erp',            icon: Wallet,        label: 'School ERP',   needs: null },
  { path: '/erp/attendance', icon: ClipboardCheck, label: 'Attendance',  needs: ['attendance.mark', 'attendance.view'] },
  { path: '/erp/admissions', icon: UserPlus,      label: 'Admissions',   needs: ['admission.view'] },
  { path: '/erp/students',   icon: Users,         label: 'Students',     needs: ['student.view'] },
  { path: '/erp/families',   icon: Home,          label: 'Families',     needs: ['family.view'] },
  { path: '/erp/staff',      icon: GraduationCap, label: 'Staff',        needs: ['employee.view'] },
  { path: '/erp/classes',    icon: Building2,     label: 'Classes',      needs: ['student.view', 'class.manage'] },
  { path: '/erp/fees',       icon: Banknote,      label: 'Fee collection', needs: ['fee.collect'] },
  { path: '/erp/defaulters', icon: AlertCircle,   label: 'Defaulters',   needs: ['fee.report'] },
  { path: '/erp/fees/setup', icon: Coins,         label: 'Fee setup',    needs: ['fee.structure'] },
  { path: '/erp/payroll',    icon: Wallet,        label: 'Payroll',      needs: ['payroll.run', 'payroll.structure', 'payroll.report'] },
  { path: '/erp/accounts',   icon: Scale,         label: 'Accounts',     needs: ['accounts.view'] },
  { path: '/erp/marks',      icon: PenLine,       label: 'Marks entry',  needs: ['exam.marks.enter', 'exam.marks.review'] },
  { path: '/erp/results',    icon: Trophy,        label: 'Results',      needs: ['exam.ledger', 'exam.configure'] },
];
const erpOwnerNav = [
  { path: '/erp/access',   icon: ShieldCheck, label: 'People & access' },
  { path: '/erp/settings', icon: Settings,    label: 'ERP settings' },
];

const allowedErpNav = (erp) => {
  const held = new Set(erp?.permissions || []);
  return erpNav.filter((item) => !item.needs || item.needs.some((p) => held.has(p)));
};

// One status call per session, shared by every mount of the layout — asking on
// every page change would add a request to every navigation for no new answer.
//
// Students are never asked at all. There are 755 of them against a backend
// running a single worker, and a student cannot hold an ERP role in this phase,
// so the answer is known without a round trip.
let erpStatusPromise = null;
const getErpStatus = (role) => {
  if (role === 'student') return Promise.resolve({ available: false });
  if (!erpStatusPromise) {
    erpStatusPromise = erpAPI.status().then(({ data }) => data).catch(() => ({ available: false }));
  }
  return erpStatusPromise;
};

// Role accent gradients (used for active nav glow, logo ring, avatar)
const roleAccent = {
  student: 'from-brand-blue via-brand-cyan to-brand-teal',
  teacher: 'from-emerald-500 via-teal-400 to-brand-cyan',
  admin:   'from-brand-purple via-brand-violet to-brand-blue',
};

export default function Layout({ children, title }) {
  const { user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const [erp, setErp] = useState(null);
  useEffect(() => { getErpStatus(user?.role).then(setErp); }, [user?.role]);

  const navItems = [
    ...(navConfig[user?.role] || []),
    ...(erp?.available ? allowedErpNav(erp) : []),
    ...(erp?.available && erp?.is_owner ? erpOwnerNav : []),
  ];
  const accent = roleAccent[user?.role] || roleAccent.student;

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const SidebarContent = () => (
    <div className="h-full flex flex-col glass-strong rounded-3xl overflow-hidden">
      {/* Brand */}
      <div className="p-5 border-b border-line/60">
        <div className="flex items-center gap-3">
          <div className="relative">
            <div className={`absolute -inset-1 rounded-2xl bg-gradient-to-br ${accent} blur opacity-60 animate-glow-pulse`} />
            <div className="relative w-11 h-11 rounded-2xl overflow-hidden flex items-center justify-center bg-white">
              <img src="/logo.jpeg" alt="LSS Logo" className="w-full h-full object-contain" style={{ mixBlendMode: 'multiply' }} />
            </div>
          </div>
          <div>
            <div className="font-display font-bold text-base leading-tight text-ink">{SCHOOL_NAME}</div>
            <div className="text-xs flex items-center gap-1 text-gradient-soft font-semibold">
              <Sparkles size={11} className="text-brand-cyan" /> AI Learning Platform
            </div>
          </div>
        </div>
      </div>

      {/* User info */}
      <div className="p-4 border-b border-line/60">
        <div className="flex items-center gap-3">
          <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${accent} flex items-center justify-center text-base font-bold text-white shadow-glow`}>
            {user?.name?.charAt(0)?.toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-sm truncate text-ink">{user?.name}</div>
            <div className="flex items-center gap-1.5 mt-0.5">
              <span className="text-[11px] px-2 py-0.5 rounded-full capitalize glass text-ink/80">
                {user?.role}
              </span>
              {user?.class_name && (
                <span className="text-[11px] text-muted">{user.class_name}</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-3 overflow-y-auto">
        <div className="space-y-1.5">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = location.pathname === item.path;
            return (
              <Link
                key={item.path}
                to={item.path}
                onClick={() => setSidebarOpen(false)}
                className="relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm transition-colors group"
              >
                {active && (
                  <motion.span
                    layoutId="nav-active"
                    transition={{ type: 'spring', stiffness: 400, damping: 32 }}
                    className={`absolute inset-0 rounded-xl bg-gradient-to-r ${accent} opacity-90 shadow-glow`}
                  />
                )}
                <span className={`relative z-10 flex items-center gap-3 ${active ? 'text-white font-semibold' : 'text-muted group-hover:text-ink'}`}>
                  <Icon size={18} />
                  <span>{item.label}</span>
                </span>
              </Link>
            );
          })}
        </div>
      </nav>

      {/* Footer */}
      <div className="p-3 border-t border-line/60">
        <button
          onClick={handleLogout}
          className="w-full flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm
                     text-muted hover:text-rose-400 hover:bg-rose-500/10 transition-all"
        >
          <LogOut size={18} />
          <span>Sign Out</span>
        </button>
      </div>
    </div>
  );

  return (
    <div className="relative min-h-screen flex text-ink">
      <AuroraBackground />

      {/* Desktop Sidebar */}
      <aside className="hidden lg:flex flex-col w-72 shrink-0 h-screen sticky top-0 p-3">
        <SidebarContent />
      </aside>

      {/* Mobile Drawer */}
      <AnimatePresence>
        {sidebarOpen && (
          <div className="lg:hidden fixed inset-0 z-40">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm"
              onClick={() => setSidebarOpen(false)}
            />
            <motion.aside
              initial={{ x: '-100%' }}
              animate={{ x: 0 }}
              exit={{ x: '-100%' }}
              transition={{ type: 'spring', stiffness: 380, damping: 38 }}
              className="absolute left-0 top-0 bottom-0 w-72 p-3"
            >
              <SidebarContent />
            </motion.aside>
          </div>
        )}
      </AnimatePresence>

      {/* Main Content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top Bar */}
        <header className="sticky top-0 z-30 glass border-b border-line/60 px-4 lg:px-6 py-3 flex items-center gap-3">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden h-9 w-9 inline-flex items-center justify-center rounded-xl glass-strong text-ink"
            aria-label="Open menu"
          >
            <Menu size={18} />
          </button>
          <h1 className="font-display font-bold text-ink flex-1 text-base lg:text-xl truncate">
            {title}
          </h1>
          <div className="flex items-center gap-2.5">
            <ThemeToggle />
            <span className="hidden sm:block text-sm text-muted">{user?.name}</span>
            <div className={`w-9 h-9 rounded-xl bg-gradient-to-br ${accent} flex items-center justify-center text-white text-sm font-bold shadow-glow`}>
              {user?.name?.charAt(0)?.toUpperCase()}
            </div>
          </div>
        </header>

        {/* Page Content */}
        <main className="flex-1 p-4 lg:p-6 overflow-auto">
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.35, ease: 'easeOut' }}
          >
            {children}
          </motion.div>
        </main>
      </div>
    </div>
  );
}
