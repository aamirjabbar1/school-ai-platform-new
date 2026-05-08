import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import Layout from '../../components/Layout';
import { useAuth } from '../../context/AuthContext';
import { assignmentAPI, questionPaperAPI } from '../../services/api';
import { ClipboardList, FileText, Users, BookOpen, Plus, ArrowRight, CheckCircle, Clock } from 'lucide-react';

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
      <div className="bg-gradient-to-r from-emerald-600 to-emerald-800 rounded-2xl p-6 text-white mb-6">
        <h2 className="text-xl font-bold">Welcome, {user?.name?.split(' ')[0]}! 👋</h2>
        <p className="text-emerald-100 text-sm mt-1">
          {user?.subjects?.join(', ') || 'Teacher'} •{' '}
          {new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
        </p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[
          { label: 'Total Assignments', value: assignments.length, icon: ClipboardList, color: 'blue' },
          { label: 'Pending Reviews', value: pendingSubmissions, icon: Clock, color: 'yellow' },
          { label: 'Question Papers', value: papers.length, icon: FileText, color: 'purple' },
          { label: 'Published Papers', value: papers.filter((p) => p.is_published).length, icon: CheckCircle, color: 'green' },
        ].map(({ label, value, icon: Icon, color }) => (
          <div key={label} className="card">
            <div className={`w-10 h-10 rounded-xl bg-${color}-100 flex items-center justify-center mb-3`}>
              <Icon size={20} className={`text-${color}-600`} />
            </div>
            <div className="text-2xl font-bold text-gray-900">{value}</div>
            <div className="text-sm text-gray-500">{label}</div>
          </div>
        ))}
      </div>

      {/* Quick Actions */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        <Link to="/teacher/assignments/create" className="card hover:shadow-md transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 bg-blue-100 rounded-xl flex items-center justify-center group-hover:bg-blue-200">
            <Plus size={24} className="text-blue-600" />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-gray-800">Create Assignment</div>
            <div className="text-sm text-gray-500">AI-assisted assignment creation</div>
          </div>
          <ArrowRight size={18} className="text-gray-400 group-hover:text-blue-600" />
        </Link>
        <Link to="/teacher/question-papers" className="card hover:shadow-md transition-shadow group cursor-pointer flex items-center gap-4">
          <div className="w-12 h-12 bg-purple-100 rounded-xl flex items-center justify-center group-hover:bg-purple-200">
            <FileText size={24} className="text-purple-600" />
          </div>
          <div className="flex-1">
            <div className="font-semibold text-gray-800">Generate Exam Paper</div>
            <div className="text-sm text-gray-500">AI-generated with answer keys</div>
          </div>
          <ArrowRight size={18} className="text-gray-400 group-hover:text-purple-600" />
        </Link>
      </div>

      {/* Recent Assignments */}
      <div className="card">
        <div className="flex items-center justify-between mb-4">
          <h3 className="font-semibold text-gray-800">Recent Assignments</h3>
          <Link to="/teacher/assignments/create" className="btn-primary text-sm py-1.5 flex items-center gap-1.5">
            <Plus size={14} /> New
          </Link>
        </div>
        {loading ? (
          <div className="space-y-3">
            {[1,2,3].map((i) => <div key={i} className="h-16 bg-gray-100 rounded-lg animate-pulse" />)}
          </div>
        ) : assignments.length === 0 ? (
          <div className="text-center py-8 text-gray-400">
            <ClipboardList size={32} className="mx-auto mb-2 opacity-40" />
            <p className="text-sm">No assignments created yet</p>
          </div>
        ) : (
          <div className="space-y-2">
            {assignments.slice(0, 6).map((a) => {
              const submissionCount = (a.submissions || []).length;
              const pendingCount = (a.submissions || []).filter((s) => s.status === 'submitted').length;
              return (
                <div key={a.id} className="flex items-center justify-between p-3 rounded-lg bg-gray-50 hover:bg-gray-100">
                  <div className="min-w-0">
                    <div className="font-medium text-sm text-gray-800 truncate">{a.title}</div>
                    <div className="text-xs text-gray-500">{a.subject} • {a.class_name}</div>
                  </div>
                  <div className="ml-3 text-right shrink-0">
                    <div className="text-xs text-gray-500">{submissionCount} submitted</div>
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
