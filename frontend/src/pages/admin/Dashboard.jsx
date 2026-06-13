import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../../components/Layout';
import StatCard from '../../components/StatCard';
import { adminAPI } from '../../services/api';
import { Users, Database, FileText, MessageSquare, BookOpen, TrendingUp, ArrowRight, Activity } from 'lucide-react';

export default function AdminDashboard() {
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    adminAPI.getDashboard().then(({ data }) => setStats(data)).finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <Layout title="Admin Dashboard">
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {[1,2,3,4,5,6,7,8].map((i) => <div key={i} className="h-28 bg-surface-3/60 rounded-2xl animate-pulse" />)}
        </div>
      </Layout>
    );
  }

  const u = stats?.users || {};
  const c = stats?.content || {};

  const statCards = [
    { label: 'Total Students', value: u.students || 0, icon: Users, color: 'blue', sub: 'registered' },
    { label: 'Total Teachers', value: u.teachers || 0, icon: Users, color: 'emerald', sub: 'registered' },
    { label: 'Knowledge Base', value: c.ingested_docs || 0, icon: Database, color: 'purple', sub: `${c.total_chunks || 0} chunks` },
    { label: 'Active Assignments', value: c.active_assignments || 0, icon: BookOpen, color: 'orange', sub: 'across all classes' },
    { label: 'Question Papers', value: c.question_papers || 0, icon: FileText, color: 'pink', sub: 'created' },
    { label: 'Pending Submissions', value: c.pending_submissions || 0, icon: Activity, color: 'yellow', sub: 'to be graded' },
    { label: 'AI Chats Today', value: c.chats_today || 0, icon: MessageSquare, color: 'teal', sub: 'messages' },
    { label: 'Total Users', value: u.total_users || 0, icon: TrendingUp, color: 'gray', sub: `${u.inactive_users || 0} inactive` },
  ];

  return (
    <Layout title="Admin Dashboard">
      {/* Welcome Banner */}
      <div className="relative overflow-hidden rounded-3xl p-6 text-white mb-6 shadow-glow-lg">
        <div className="absolute inset-0 bg-gradient-to-br from-brand-purple via-brand-violet to-brand-blue" />
        <div className="absolute -bottom-16 -right-10 w-56 h-56 rounded-full bg-white/15 blur-3xl animate-float" />
        <div className="relative z-10">
          <h2 className="font-display text-2xl font-bold">System Overview</h2>
          <p className="text-white/85 text-sm mt-1">
            Platform Health: <span className="text-white font-semibold inline-flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-300 animate-pulse" />Online
            </span> •{' '}
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {statCards.map(({ label, value, icon: Icon, color, sub }, i) => (
          <StatCard key={label} icon={Icon} value={value} label={label} sub={sub} color={color} delay={i * 0.05} />
        ))}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <Link to="/admin/users" className="card hover:shadow-glow transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-brand-blue to-brand-cyan flex items-center justify-center text-white shadow-glow group-hover:scale-105 transition-transform">
            <Users size={24} />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-ink">Manage Users</div>
            <div className="text-sm text-muted">Add students, teachers, and admins</div>
          </div>
          <ArrowRight size={18} className="text-faint group-hover:text-brand-cyan group-hover:translate-x-1 transition-all" />
        </Link>
        <Link to="/admin/knowledge-base" className="card hover:shadow-glow transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-brand-violet to-brand-purple flex items-center justify-center text-white shadow-glow group-hover:scale-105 transition-transform">
            <Database size={24} />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-ink">Knowledge Base</div>
            <div className="text-sm text-muted">Upload books and curriculum materials</div>
          </div>
          <ArrowRight size={18} className="text-faint group-hover:text-brand-purple group-hover:translate-x-1 transition-all" />
        </Link>
      </div>

      {/* Recent Activity */}
      <div className="card">
        <h3 className="font-semibold text-ink mb-4">Recent Activity</h3>
        {!stats?.recent_activity?.length ? (
          <p className="text-faint text-sm text-center py-4">No recent activity</p>
        ) : (
          <div className="space-y-3">
            {stats.recent_activity.map((item, i) => (
              <div key={i} className="flex items-center gap-3 p-2 rounded-lg hover:bg-surface-3/60">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0
                  ${item.type === 'submission' ? 'bg-blue-100 text-blue-600' : 'bg-purple-100 text-purple-600'}`}>
                  {item.type === 'submission' ? <BookOpen size={14} /> : <Database size={14} />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-ink truncate">
                    <span className="font-medium">{item.user_name}</span>{' '}
                    {item.type === 'submission' ? 'submitted' : 'uploaded'}{' '}
                    <span className="text-muted">"{item.context}"</span>
                  </p>
                  <p className="text-xs text-faint">{(() => { const raw = item.created_at || item.ts; if (!raw) return ''; const d = new Date(raw.replace(/(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+([+-])/, '$1$2')); return isNaN(d) ? '' : d.toLocaleString(); })()}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
