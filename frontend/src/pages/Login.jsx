import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { GraduationCap, Eye, EyeOff, Loader2, BookOpen, Brain, Shield } from 'lucide-react';

const SCHOOL_NAME = import.meta.env.VITE_SCHOOL_NAME || 'School AI Platform';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ login_id: '', password: '' });
  const [showPass, setShowPass] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      const user = await login(form);
      const routes = { student: '/student/dashboard', teacher: '/teacher/dashboard', admin: '/admin/dashboard' };
      navigate(routes[user.role] || '/');
    } catch (err) {
      setError(err.response?.data?.error || 'Login failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex">
      {/* Left Panel */}
      <div className="hidden lg:flex w-1/2 bg-gradient-to-br from-blue-800 to-blue-950 text-white flex-col justify-between p-12">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 bg-white rounded-xl overflow-hidden flex items-center justify-center">
            <img src="/logo.jpeg" alt="LSS Logo" className="w-full h-full object-contain" style={{mixBlendMode:'multiply'}} />
          </div>
          <div>
            <div className="font-bold text-lg">{SCHOOL_NAME}</div>
            <div className="text-blue-300 text-xs">AI Learning Platform</div>
          </div>
        </div>

        <div className="space-y-8">
          <div>
            <h1 className="text-4xl font-bold leading-tight mb-4">
              Empowering Education<br />with Artificial Intelligence
            </h1>
            <p className="text-blue-200 text-lg">
              A smart learning platform designed specifically for students, teachers, and staff — powered by AI, guided by curriculum.
            </p>
          </div>

          <div className="space-y-4">
            {[
              { icon: Brain, title: 'Curriculum-Aligned AI', desc: 'Answers strictly from school books and materials' },
              { icon: BookOpen, title: 'Smart Assignments', desc: 'AI-generated assignments aligned to your syllabus' },
              { icon: Shield, title: 'Secure & Private', desc: 'Role-based access for students, teachers & admins' },
            ].map(({ icon: Icon, title, desc }) => (
              <div key={title} className="flex items-start gap-3 p-3 bg-white/10 rounded-xl">
                <div className="w-9 h-9 bg-white/20 rounded-lg flex items-center justify-center shrink-0">
                  <Icon size={18} />
                </div>
                <div>
                  <div className="font-semibold text-sm">{title}</div>
                  <div className="text-blue-200 text-xs">{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="text-blue-400 text-xs">
          © {new Date().getFullYear()} {SCHOOL_NAME}. All rights reserved.
        </div>
      </div>

      {/* Right Panel - Login Form */}
      <div className="flex-1 flex items-center justify-center p-6 bg-gray-50">
        <div className="w-full max-w-md">
          {/* Mobile Logo */}
          <div className="lg:hidden text-center mb-8">
            <div className="w-16 h-16 bg-white rounded-2xl overflow-hidden flex items-center justify-center mx-auto mb-3 shadow">
              <img src="/logo.jpeg" alt="LSS Logo" className="w-full h-full object-contain" style={{mixBlendMode:'multiply'}} />
            </div>
            <h1 className="text-xl font-bold text-gray-900">{SCHOOL_NAME}</h1>
            <p className="text-gray-500 text-sm">AI Learning Platform</p>
          </div>

          <div className="card">
            <div className="mb-6">
              <h2 className="text-2xl font-bold text-gray-900">Welcome back</h2>
              <p className="text-gray-500 text-sm mt-1">Sign in to your account to continue</p>
            </div>

            {error && (
              <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2">
                <div className="w-2 h-2 bg-red-500 rounded-full shrink-0" />
                <p className="text-red-700 text-sm">{error}</p>
              </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Student / Teacher ID
                </label>
                <input
                  type="text"
                  value={form.login_id}
                  onChange={(e) => setForm({ ...form, login_id: e.target.value })}
                  placeholder="Enter your ID (e.g. STU001)"
                  className="input-field"
                  required
                  autoFocus
                />
              </div>

              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Password
                </label>
                <div className="relative">
                  <input
                    type={showPass ? 'text' : 'password'}
                    value={form.password}
                    onChange={(e) => setForm({ ...form, password: e.target.value })}
                    placeholder="Enter your password"
                    className="input-field pr-10"
                    required
                  />
                  <button
                    type="button"
                    onClick={() => setShowPass(!showPass)}
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  >
                    {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="btn-primary w-full flex items-center justify-center gap-2 py-2.5 mt-2"
              >
                {loading ? (
                  <><Loader2 size={18} className="animate-spin" /> Signing in...</>
                ) : (
                  'Sign In'
                )}
              </button>
            </form>

            <div className="mt-6 pt-5 border-t border-gray-100">
              <p className="text-xs text-gray-500 text-center mb-3">Demo Credentials</p>
              <div className="grid grid-cols-3 gap-2 text-xs">
                {[
                  { role: 'Admin', id: 'admin001', pass: 'admin123', color: 'purple' },
                  { role: 'Teacher', id: 'TCH001', pass: 'teacher123', color: 'emerald' },
                  { role: 'Student', id: 'STU001', pass: 'student123', color: 'blue' },
                ].map(({ role, id, pass, color }) => (
                  <button
                    key={role}
                    onClick={() => setForm({ login_id: id, password: pass })}
                    className={`p-2 rounded-lg border text-left transition-colors
                      bg-${color}-50 border-${color}-100 hover:bg-${color}-100 text-${color}-700`}
                  >
                    <div className="font-semibold">{role}</div>
                    <div className="text-xs opacity-70">{id}</div>
                  </button>
                ))}
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
