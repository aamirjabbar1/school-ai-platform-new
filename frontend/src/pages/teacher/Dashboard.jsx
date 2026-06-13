import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../../components/Layout';
import StatCard from '../../components/StatCard';
import { useAuth } from '../../context/AuthContext';
import { assignmentAPI, questionPaperAPI } from '../../services/api';
import { ClipboardList, FileText, Plus, ArrowRight, CheckCircle, Clock } from 'lucide-react';

export default function TeacherDashboard() {
  const { user } = useAuth();
  const [assignments, setAssignments] = useState([]);
  const [papers, setPapers] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    Promise.all([
      assignmentAPI.getAll(),
      questionPaperAPI.getAll(),
    ]).then(([{ data: asgn }, { data: pap }]) => {
      setAssignments(asgn);
      setPapers(pap);
    }).finally(() => setLoading(false));
  }, []);

  const pendingSubmissions = assignments.reduce((acc, a) => {
    const pending = (a.submissions || []).filter((s) => s.status === 'submitted');
    return acc + pending.length;
  }, 0);

  return (
    <Layout title="Teacher Dashboard">
      {/* Welcome */}
      <div className="relative overflow-hidden rounded-3xl p-6 text-white mb-6 shadow-glow-lg">
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-600 via-teal-600 to-brand-cyan" />
        <div className="absolute -bottom-16 -right-10 w-56 h-56 rounded-full bg-white/15 blur-3xl animate-float" />
        <div className="relative z-10">
          <h2 className="font-display text-2xl font-bold">Welcome, {user?.name?.split(' ')[0]}! 👋</h2>
          <p className="text-white/85 text-sm mt-1">
            {user?.subjects?.join(', ') || 'Teacher'} •{' '}
            {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
          </p>
        </div>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: 'Total Assignments', value: assignments.length, icon: ClipboardList, color: 'blue' },
          { label: 'Pending Reviews', value: pendingSubmissions, icon: Clock, color: 'yellow' },
          { label: 'Question Papers', value: papers.length, icon: FileText, color: 'purple' },
          { label: 'Published Papers', value: papers.filter((p) => p.is_published).length, icon: CheckCircle, color: 'green' },
        ].map(({ label, value, icon: Icon, color }, i) => (
          <StatCard key={label} icon={Icon} value={value} label={label} color={color} delay={i * 0.06} />
        ))}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <Link to="/teacher/assignments/create" className="card hover:shadow-glow transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-brand-blue to-brand-cyan flex items-center justify-center text-white shadow-glow group-hover:scale-105 transition-transform">
            <Plus size={24} />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-ink">Create Assignment</div>
            <div className="text-sm text-muted">AI-assisted assignment creation</div>
          </div>
          <ArrowRight size={18} className="text-faint group-hover:text-brand-cyan group-hover:translate-x-1 transition-all" />
        </Link>
        <Link to="/teacher/question-papers" className="card hover:shadow-glow transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-gradient-to-br from-brand-violet to-brand-purple flex items-center justify-center text-white shadow-glow group-hover:scale-105 transition-transform">
            <FileText size={24} />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-ink">Generate Exam Paper</div>
            <div className="text-sm text-muted">AI-generated with answer keys</div>
          </div>
          <ArrowRight size={18} className="text-faint group-hover:text-brand-purple group-hover:translate-x-1 transition-all" />
        </Link>
      </div>

      {/* Recent Assignments */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-ink">Recent Assignments</h3>
          <Link to="/teacher/assignments/create" className="btn-primary text-sm py-1.5 flex items-center gap-1.5">
            <Plus size={14} /> New
          </Link>
        </div>
        {loading ? (
          <div className="space-y-3">
            {[1,2,3].map((i) => <div key={i} className="h-16 bg-surface-3 rounded-lg animate-pulse" />)}
          </div>
        ) : assignments.length === 0 ? (
          <div className="text-center py-8 text-faint">
            <ClipboardList size={32} className="mx-auto mb-2 opacity-40" />
            <p className="text-sm">No assignments created yet</p>
          </div>
        ) : (
          <div className="space-y-2">
            {assignments.slice(0, 6).map((a) => {
              const submissionCount = (a.submissions || []).length;
              const pendingCount = (a.submissions || []).filter((s) => s.status === 'submitted').length;
              return (
                <div key={a.id} className="flex items-center justify-between p-3 rounded-lg bg-surface-3/60 hover:bg-surface-3">
                  <div className="min-w-0">
                    <div className="font-medium text-sm text-ink truncate">{a.title}</div>
                    <div className="text-xs text-muted">{a.subject} • {a.class_name}</div>
                  </div>
                  <div className="ml-3 text-right shrink-0">
                    <div className="text-xs text-muted">{submissionCount} submitted</div>
                    {pendingCount > 0 && (
                      <span className="badge-yellow">{pendingCount} to review</span>
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
