import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../../components/Layout';
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
      <div className="bg-gradient-to-r from-blue-600 to-blue-800 rounded-2xl p-6 text-white mb-6">
        <h2 className="text-xl font-bold">Welcome back, {user?.name?.split(' ')[0]}! 👋</h2>
        <p className="text-blue-100 text-sm mt-1">
          {user?.class_name} • {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
        </p>
        {overdue.length > 0 && (
          <div className="mt-3 flex items-center gap-2 text-yellow-200 text-sm">
            <AlertCircle size={16} />
            <span>You have {overdue.length} overdue assignment{overdue.length > 1 ? 's' : ''}!</span>
          </div>
        )}
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: 'Pending', value: pending.length, icon: Clock, color: 'yellow', sub: 'assignments' },
          { label: 'Submitted', value: submitted.length, icon: CheckCircle, color: 'blue', sub: 'assignments' },
          { label: 'Graded', value: graded.length, icon: Trophy, color: 'green', sub: 'assignments' },
          { label: 'Avg Score', value: avgGrade ? `${avgGrade}%` : '—', icon: Trophy, color: 'purple', sub: 'overall' },
        ].map(({ label, value, icon: Icon, color, sub }) => (
          <div key={label} className="card">
            <div className={`w-10 h-10 rounded-xl bg-${color}-100 flex items-center justify-center mb-3`}>
              <Icon size={20} className={`text-${color}-600`} />
            </div>
            <div className="text-2xl font-bold text-gray-900">{value}</div>
            <div className="text-sm text-gray-500">{label}</div>
            <div className="text-xs text-gray-400">{sub}</div>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <Link to="/student/chat" className="card hover:shadow-md transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 bg-blue-100 rounded-xl flex items-center justify-center group-hover:bg-blue-200 transition-colors">
            <MessageSquare size={24} className="text-blue-600" />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-gray-800">AI Study Assistant</div>
            <div className="text-sm text-gray-500">Ask questions, get notes, prepare answers</div>
          </div>
          <ArrowRight size={18} className="text-gray-400 group-hover:text-blue-600 transition-colors" />
        </Link>
        <Link to="/student/assignments" className="card hover:shadow-md transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 bg-green-100 rounded-xl flex items-center justify-center group-hover:bg-green-200 transition-colors">
            <BookOpen size={24} className="text-green-600" />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-gray-800">My Assignments</div>
            <div className="text-sm text-gray-500">{pending.length} pending, {overdue.length} overdue</div>
          </div>
          <ArrowRight size={18} className="text-gray-400 group-hover:text-green-600 transition-colors" />
        </Link>
      </div>

      {/* Recent Assignments */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-800">Recent Assignments</h3>
          <Link to="/student/assignments" className="text-sm text-blue-600 hover:text-blue-700 flex items-center gap-1">
            View all <ArrowRight size={14} />
          </Link>
        </div>
        {loading ? (
          <div className="space-y-3">
            {[1,2,3].map((i) => <div key={i} className="h-16 bg-gray-100 rounded-lg animate-pulse" />)}
          </div>
        ) : assignments.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            <ClipboardList size={32} className="mx-auto mb-2 opacity-40" />
            <p className="text-sm">No assignments yet</p>
          </div>
        ) : (
          <div className="space-y-3">
            {assignments.slice(0, 5).map((a) => {
              const status = a.my_submission?.status;
              const isOverdue = a.due_date && new Date(a.due_date) < new Date() && !status;
              return (
                <div key={a.id} className="flex items-center justify-between p-3 rounded-lg bg-gray-50 hover:bg-gray-100 transition-colors">
                  <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm text-gray-800 truncate">{a.title}</div>
                    <div className="text-xs text-gray-500">{a.subject} • {a.assignment_type}</div>
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
