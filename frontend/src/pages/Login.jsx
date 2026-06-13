import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../context/AuthContext';
import AuroraBackground from '../components/AuroraBackground';
import ThemeToggle from '../components/ThemeToggle';
import { Eye, EyeOff, Loader2, BookOpen, Brain, Shield, Sparkles, ArrowRight } from 'lucide-react';

const SCHOOL_NAME = import.meta.env.VITE_SCHOOL_NAME || 'School AI Platform';

const FEATURES = [
  { icon: Brain, title: 'Curriculum-Aligned AI', desc: 'Answers grounded in your school books' },
  { icon: BookOpen, title: 'Smart Assignments', desc: 'AI-built tasks matched to your syllabus' },
  { icon: Shield, title: 'Secure & Private', desc: 'Role-based access for the whole school' },
];

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
      navigate(routes[user.role] || '/', { replace: true });
    } catch (err) {
      setError(err.response?.data?.error || 'Login failed. Please check your credentials.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="relative min-h-screen flex items-center justify-center p-4 text-ink overflow-hidden">
      <AuroraBackground stars={48} />

      <div className="absolute top-4 right-4 z-20">
        <ThemeToggle />
      </div>

      <motion.div
        initial={{ opacity: 0, y: 20, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
        className="w-full max-w-5xl grid lg:grid-cols-2 rounded-4xl overflow-hidden glass-strong shadow-glow-lg"
      >
        {/* Brand panel */}
        <div className="relative hidden lg:flex flex-col justify-between p-10 overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-br from-brand-blue/90 via-brand-violet/80 to-brand-teal/70" />
          <div className="absolute -bottom-24 -right-24 w-72 h-72 rounded-full bg-white/15 blur-3xl animate-float" />
          <div className="relative z-10 flex items-center gap-3 text-white">
            <div className="w-12 h-12 bg-white rounded-2xl overflow-hidden flex items-center justify-center">
              <img src="/logo.jpeg" alt="LSS Logo" className="w-full h-full object-contain" style={{ mixBlendMode: 'multiply' }} />
            </div>
            <div>
              <div className="font-display font-bold text-lg">{SCHOOL_NAME}</div>
              <div className="text-white/80 text-xs flex items-center gap-1">
                <Sparkles size={11} /> AI Learning Platform
              </div>
            </div>
          </div>

          <div className="relative z-10 text-white space-y-7">
            <div>
              <h1 className="font-display text-4xl font-bold leading-tight mb-3">
                Learning, <span className="text-yellow-200">reimagined</span> with AI
              </h1>
              <p className="text-white/85 text-base">
                Your personal AI tutor — guided by your curriculum, available any time, for every subject.
              </p>
            </div>
            <div className="space-y-3">
              {FEATURES.map(({ icon: Icon, title, desc }, i) => (
                <motion.div
                  key={title}
                  initial={{ opacity: 0, x: -16 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: 0.3 + i * 0.12 }}
                  className="flex items-start gap-3 p-3 rounded-2xl bg-white/10 backdrop-blur-sm border border-white/15"
                >
                  <div className="w-9 h-9 bg-white/20 rounded-xl flex items-center justify-center shrink-0">
                    <Icon size={18} />
                  </div>
                  <div>
                    <div className="font-semibold text-sm">{title}</div>
                    <div className="text-white/75 text-xs">{desc}</div>
                  </div>
                </motion.div>
              ))}
            </div>
          </div>

          <div className="relative z-10 text-white/60 text-xs">
            © {new Date().getFullYear()} {SCHOOL_NAME}. All rights reserved.
          </div>
        </div>

        {/* Login form */}
        <div className="flex items-center justify-center p-7 sm:p-10">
          <div className="w-full max-w-sm">
            {/* Mobile brand */}
            <div className="lg:hidden text-center mb-7">
              <div className="w-16 h-16 bg-white rounded-2xl overflow-hidden flex items-center justify-center mx-auto mb-3 shadow-glow">
                <img src="/logo.jpeg" alt="LSS Logo" className="w-full h-full object-contain" style={{ mixBlendMode: 'multiply' }} />
              </div>
              <h1 className="font-display text-xl font-bold text-ink">{SCHOOL_NAME}</h1>
              <p className="text-muted text-sm">AI Learning Platform</p>
            </div>

            <div className="mb-6">
              <h2 className="font-display text-2xl font-bold text-ink">Welcome back 👋</h2>
              <p className="text-muted text-sm mt-1">Sign in to continue your learning journey</p>
            </div>

            {error && (
              <motion.div
                initial={{ opacity: 0, y: -6 }}
                animate={{ opacity: 1, y: 0 }}
                className="mb-4 p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl flex items-center gap-2"
              >
                <div className="w-2 h-2 bg-rose-500 rounded-full shrink-0" />
                <p className="text-rose-500 dark:text-rose-300 text-sm">{error}</p>
              </motion.div>
            )}

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-ink/80 mb-1.5">
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
                <label className="block text-sm font-medium text-ink/80 mb-1.5">
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
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-faint hover:text-ink transition-colors"
                    aria-label={showPass ? 'Hide password' : 'Show password'}
                  >
                    {showPass ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <button
                type="submit"
                disabled={loading}
                className="btn-primary w-full py-2.5 mt-2 text-base"
              >
                {loading ? (
                  <><Loader2 size={18} className="animate-spin" /> Signing in...</>
                ) : (
                  <>Sign In <ArrowRight size={18} /></>
                )}
              </button>
            </form>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
