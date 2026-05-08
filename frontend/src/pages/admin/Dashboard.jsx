import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../../components/Layout';
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
          {[1,2,3,4,5,6,7,8].map((i) => <div key={i} className="h-28 bg-gray-100 rounded-xl animate-pulse" />)}
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
      <div className="bg-gradient-to-r from-purple-600 to-purple-900 rounded-2xl p-6 text-white mb-6">
        <h2 className="text-xl font-bold">System Overview</h2>
        <p className="text-purple-200 text-sm mt-1">
          Platform Health: <span className="text-white font-semibold">Online</span> •{' '}
          {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
        </p>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {statCards.map(({ label, value, icon: Icon, color, sub }) => (
          <div key={label} className="card">
            <div className={`w-10 h-10 rounded-xl bg-${color}-100 flex items-center justify-center mb-3`}>
              <Icon size={20} className={`text-${color}-600`} />
            </div>
            <div className="text-2xl font-bold text-gray-900">{value}</div>
            <div className="text-sm font-medium text-gray-700">{label}</div>
            <div className="text-xs text-gray-400">{sub}</div>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <Link to="/admin/users" className="card hover:shadow-md transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 bg-blue-100 rounded-xl flex items-center justify-center group-hover:bg-blue-200">
            <Users size={24} className="text-blue-600" />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-gray-800">Manage Users</div>
            <div className="text-sm text-gray-500">Add students, teachers, and admins</div>
          </div>
          <ArrowRight size={18} className="text-gray-400 group-hover:text-blue-600" />
        </Link>
        <Link to="/admin/knowledge-base" className="card hover:shadow-md transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 bg-purple-100 rounded-xl flex items-center justify-center group-hover:bg-purple-200">
            <Database size={24} className="text-purple-600" />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-gray-800">Knowledge Base</div>
            <div className="text-sm text-gray-500">Upload books and curriculum materials</div>
          </div>
          <ArrowRight size={18} className="text-gray-400 group-hover:text-purple-600" />
        </Link>
      </div>

      {/* Recent Activity */}
      <div className="card">
        <h3 className="font-semibold text-gray-800 mb-4">Recent Activity</h3>
        {!stats?.recent_activity?.length ? (
          <p className="text-gray-400 text-sm text-center py-4">No recent activity</p>
        ) : (
          <div className="space-y-3">
            {stats.recent_activity.map((item, i) => (
              <div key={i} className="flex items-center gap-3 p-2 rounded-lg hover:bg-gray-50">
                <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0
                  ${item.type === 'submission' ? 'bg-blue-100 text-blue-600' : 'bg-purple-100 text-purple-600'}`}>
                  {item.type === 'submission' ? <BookOpen size={14} /> : <Database size={14} />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 truncate">
                    <span className="font-medium">{item.user_name}</span>{' '}
                    {item.type === 'submission' ? 'submitted' : 'uploaded'}{' '}
                    <span className="text-gray-600">"{item.context}"</span>
                  </p>
                  <p className="text-xs text-gray-400">{(() => { const raw = item.created_at || item.ts; if (!raw) return ''; const d = new Date(raw.replace(/(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+([+-])/, '$1$2')); return isNaN(d) ? '' : d.toLocaleString(); })()}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
