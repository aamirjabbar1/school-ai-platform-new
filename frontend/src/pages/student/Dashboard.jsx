import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../../components/Layout';
import StatCard from '../../components/StatCard';
import { useAuth } from '../../context/AuthContext';
import { assignmentAPI } from '../../services/api';
import { BookOpen, MessageSquare, ClipboardList, Clock, CheckCircle, AlertCircle, Trophy, ArrowRight } from 'lucide-react';

export default function StudentDashboard() {
  const { user } = useAuth();
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    assignmentAPI.getAll().then(({ data }) => {
      setAssignments(data);
    }).catch(console.error).finally(() => setLoading(false));
  }, []);

  const pending = assignments.filter((a) => !a.my_submission || a.my_submission.status === 'draft');
  const submitted = assignments.filter((a) => a.my_submission?.status === 'submitted');
  const graded = assignments.filter((a) => a.my_submission?.status === 'graded');
  const overdue = pending.filter((a) => a.due_date && new Date(a.due_date) < new Date());

  const avgGrade = graded.length > 0
    ? Math.round(graded.reduce((s, a) => s + (a.my_submission?.grade || 0), 0) / graded.length)
    : null;

  return (
    <Layout title="Student Dashboard">
      {/* Welcome */}
      <div className="relative overflow-hidden rounded-3xl p-6 text-white mb-6 shadow-glow-lg">
        <div className="absolute inset-0 bg-gradient-to-br from-brand-blue via-brand-violet to-brand-teal" />
        <div className="absolute -bottom-16 -right-10 w-56 h-56 rounded-full bg-white/15 blur-3xl animate-float" />
        <div className="relative z-10">
          <h2 className="font-display text-2xl font-bold">Welcome back, {user?.name?.split(' ')[0]}! 👋</h2>
          <p className="text-white/85 text-sm mt-1">
            {user?.class_name} • {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
          {overdue.length > 0 && (
            <div className="mt-3 inline-flex items-center gap-2 text-yellow-100 text-sm bg-white/15 rounded-full px-3 py-1">
              <AlertCircle size={16} />
              <span>You have {overdue.length} overdue assignment{overdue.length > 1 ? 's' : ''}!</span>
            </div>
          )}
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: 'Pending', value: pending.length, icon: Clock, color: 'yellow', sub: 'assignments' },
          { label: 'Submitted', value: submitted.length, icon: CheckCircle, color: 'blue', sub: 'assignments' },
          { label: 'Graded', value: graded.length, icon: Trophy, color: 'green', sub: 'assignments' },
          { label: 'Avg Score', value: avgGrade ? `${avgGrade}%` : '—', icon: Trophy, color: 'purple', sub: 'overall' },
        ].map(({ label, value, icon: Icon, color, sub }, i) => (
          <StatCard key={label} icon={Icon} value={value} label={label} sub={sub} color={color} delay={i * 0.06} />
        ))}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <Link to="/student/chat" className="card hover:shadow-glow transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-brand-blue to-brand-cyan flex items-center justify-center text-white shadow-glow group-hover:scale-105 transition-transform">
            <MessageSquare size={24} />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-ink">AI Study Assistant</div>
            <div className="text-sm text-muted">Ask questions, get notes, prepare answers</div>
          </div>
          <ArrowRight size={18} className="text-faint group-hover:text-brand-cyan group-hover:translate-x-1 transition-all" />
        </Link>
        <Link to="/student/assignments" className="card hover:shadow-glow transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-500 flex items-center justify-center text-white shadow-glow group-hover:scale-105 transition-transform">
            <BookOpen size={24} />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-ink">My Assignments</div>
            <div className="text-sm text-muted">{pending.length} pending, {overdue.length} overdue</div>
          </div>
          <ArrowRight size={18} className="text-faint group-hover:text-emerald-400 group-hover:translate-x-1 transition-all" />
        </Link>
      </div>

      {/* Recent Assignments */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-display font-bold text-ink">Recent Assignments</h3>
          <Link to="/student/assignments" className="text-sm text-brand-cyan hover:opacity-80 flex items-center gap-1">
            View all <ArrowRight size={14} />
          </Link>
        </div>
        {loading ? (
          <div className="space-y-3">
            {[1,2,3].map((i) => <div key={i} className="h-16 bg-surface-3/60 rounded-xl animate-pulse" />)}
          </div>
        ) : assignments.length === 0 ? (
          <div className="text-center py-8 text-faint">
            <ClipboardList size={32} className="mx-auto mb-2 opacity-40" />
            <p className="text-sm">No assignments yet</p>
          </div>
        ) : (
          <div className="space-y-3">
            {assignments.slice(0, 5).map((a) => {
              const status = a.my_submission?.status;
              const isOverdue = a.due_date && new Date(a.due_date) < new Date() && !status;
              return (
                <div key={a.id} className="flex items-center justify-between p-3 rounded-xl bg-surface-3/50 hover:bg-surface-3 transition-colors">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm text-ink truncate">{a.title}</div>
                    <div className="text-xs text-muted">{a.subject} • {a.assignment_type}</div>
                  </div>
                  <div className="ml-3 text-right shrink-0">
                    {status === 'graded' ? (
                      <span className="badge-green">{a.my_submission.grade}%</span>
                    ) : status === 'submitted' ? (
                      <span className="badge-blue">Submitted</span>
                    ) : isOverdue ? (
                      <span className="badge-red">Overdue</span>
                    ) : (
                      <span className="badge-yellow">
                        {a.due_date ? `Due ${new Date(a.due_date).toLocaleDateString()}` : 'Pending'}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Layout>
  );
}
