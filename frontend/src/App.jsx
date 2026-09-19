import { Suspense, lazy } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { AuthProvider, useAuth } from './context/AuthContext';
import { ThemeProvider } from './context/ThemeContext';

// Pages
import Login from './pages/Login';
import ForceChangePassword from './pages/ForceChangePassword';
import StudentDashboard from './pages/student/Dashboard';
import StudentChat from './pages/student/Chat';
import StudentAssignments from './pages/student/Assignments';
import StudentQuestionPapers from './pages/student/QuestionPapers';
import StudentPractice from './pages/student/Practice';
import StudentOnlineClasses from './pages/student/OnlineClasses';
const StudentClassroom = lazy(() => import('./pages/student/Classroom'));
const RecordedClasses = lazy(() => import('./pages/student/RecordedClasses'));
import ClassSummary from './pages/student/ClassSummary';
import TeacherDashboard from './pages/teacher/Dashboard';
import TeacherOnlineClasses from './pages/teacher/OnlineClasses';
const TeacherClassroom = lazy(() => import('./pages/teacher/Classroom'));
import LessonRecord from './pages/teacher/LessonRecord';
import TeacherChat from './pages/teacher/Chat';
import CreateAssignment from './pages/teacher/CreateAssignment';
import TeacherAssignments from './pages/teacher/Assignments';
import QuestionPapers from './pages/teacher/QuestionPapers';
import LessonPlans from './pages/teacher/LessonPlans';
import AdminDashboard from './pages/admin/Dashboard';
import ManageUsers from './pages/admin/ManageUsers';
import KnowledgeBase from './pages/admin/KnowledgeBase';
import CurriculumMapping from './pages/admin/CurriculumMapping';
import ContentOversight from './pages/admin/ContentOversight';
import BulkImportStudents from './pages/admin/BulkImportStudents';
import AdminLiveClasses from './pages/admin/LiveClasses';
const ObserveClass = lazy(() => import('./pages/admin/ObserveClass'));

// ERP (phase 1). Lazily loaded and route-split: the ERP must not add a byte to
// the bundle a student downloads to open the chatbot.
const ErpHome = lazy(() => import('./pages/erp/Home'));
const ErpStudents = lazy(() => import('./pages/erp/Students'));
const ErpStaff = lazy(() => import('./pages/erp/Staff'));
const ErpClasses = lazy(() => import('./pages/erp/Classes'));
const ErpAccess = lazy(() => import('./pages/erp/Access'));
const ErpSettings = lazy(() => import('./pages/erp/Settings'));

const ProtectedRoute = ({ children, allowedRoles }) => {
  const { user, loading } = useAuth();
  if (loading) return (
    <div className="min-h-screen flex items-center justify-center">
      <div className="text-center">
        <div className="w-12 h-12 border-4 border-brand-cyan border-t-transparent rounded-full animate-spin mx-auto mb-3" />
        <p className="text-muted font-medium">Loading...</p>
      </div>
    </div>
  );
  if (!user) return <Navigate to="/login" replace />;
  if (user.must_change_password) return <Navigate to="/change-password" replace />;
  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to={`/${user.role}/dashboard`} replace />;
  }
  return children;
};

// Shown while a lazily-loaded classroom is fetched. Deliberately quiet: a
// student pressing JOIN CLASS should see the lesson, not a loading essay.
const RouteFallback = () => (
  <div className="min-h-screen flex items-center justify-center">
    <div className="w-10 h-10 border-4 border-brand-cyan border-t-transparent rounded-full animate-spin" />
  </div>
);

const RoleRedirect = () => {
  const { user, loading } = useAuth();
  if (loading) return null;
  if (!user) return <Navigate to="/login" replace />;
  const routes = { student: '/student/dashboard', teacher: '/teacher/dashboard', admin: '/admin/dashboard' };
  return <Navigate to={routes[user.role] || '/login'} replace />;
};

export default function App() {
  return (
    <ThemeProvider>
      <BrowserRouter>
        <AuthProvider>
          <Suspense fallback={<RouteFallback />}>
          <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/change-password" element={<ForceChangePassword />} />
          <Route path="/" element={<RoleRedirect />} />

          {/* Student Routes */}
          <Route path="/student/dashboard" element={<ProtectedRoute allowedRoles={['student']}><StudentDashboard /></ProtectedRoute>} />
          <Route path="/student/chat" element={<ProtectedRoute allowedRoles={['student']}><StudentChat /></ProtectedRoute>} />
          <Route path="/student/assignments" element={<ProtectedRoute allowedRoles={['student']}><StudentAssignments /></ProtectedRoute>} />
          <Route path="/student/question-papers" element={<ProtectedRoute allowedRoles={['student']}><StudentQuestionPapers /></ProtectedRoute>} />
          <Route path="/student/practice" element={<ProtectedRoute allowedRoles={['student']}><StudentPractice /></ProtectedRoute>} />
          <Route path="/student/online-classes" element={<ProtectedRoute allowedRoles={['student']}><StudentOnlineClasses /></ProtectedRoute>} />
          {/* The classroom runs full-screen, outside the dashboard chrome */}
          <Route path="/student/classroom/:sessionId" element={<ProtectedRoute allowedRoles={['student']}><StudentClassroom /></ProtectedRoute>} />
          <Route path="/student/recorded-classes" element={<ProtectedRoute allowedRoles={['student']}><RecordedClasses /></ProtectedRoute>} />
          <Route path="/student/class-summary/:sessionId" element={<ProtectedRoute allowedRoles={['student']}><ClassSummary /></ProtectedRoute>} />

          {/* Teacher Routes */}
          <Route path="/teacher/dashboard" element={<ProtectedRoute allowedRoles={['teacher']}><TeacherDashboard /></ProtectedRoute>} />
          <Route path="/teacher/chat" element={<ProtectedRoute allowedRoles={['teacher']}><TeacherChat /></ProtectedRoute>} />
          <Route path="/teacher/assignments" element={<ProtectedRoute allowedRoles={['teacher']}><TeacherAssignments /></ProtectedRoute>} />
          <Route path="/teacher/assignments/create" element={<ProtectedRoute allowedRoles={['teacher']}><CreateAssignment /></ProtectedRoute>} />
          <Route path="/teacher/question-papers" element={<ProtectedRoute allowedRoles={['teacher']}><QuestionPapers /></ProtectedRoute>} />
          <Route path="/teacher/lesson-plans" element={<ProtectedRoute allowedRoles={['teacher']}><LessonPlans /></ProtectedRoute>} />
          <Route path="/teacher/online-classes" element={<ProtectedRoute allowedRoles={['teacher']}><TeacherOnlineClasses /></ProtectedRoute>} />
          <Route path="/teacher/classroom/:sessionId" element={<ProtectedRoute allowedRoles={['teacher']}><TeacherClassroom /></ProtectedRoute>} />
          <Route path="/teacher/lesson-record/:sessionId" element={<ProtectedRoute allowedRoles={['teacher']}><LessonRecord /></ProtectedRoute>} />

          {/* Admin Routes */}
          <Route path="/admin/dashboard" element={<ProtectedRoute allowedRoles={['admin']}><AdminDashboard /></ProtectedRoute>} />
          <Route path="/admin/users" element={<ProtectedRoute allowedRoles={['admin']}><ManageUsers /></ProtectedRoute>} />
          <Route path="/admin/import-students" element={<ProtectedRoute allowedRoles={['admin']}><BulkImportStudents /></ProtectedRoute>} />
          <Route path="/admin/knowledge-base" element={<ProtectedRoute allowedRoles={['admin']}><KnowledgeBase /></ProtectedRoute>} />
          <Route path="/admin/content" element={<ProtectedRoute allowedRoles={['admin']}><ContentOversight /></ProtectedRoute>} />
          <Route path="/admin/academic-settings" element={<ProtectedRoute allowedRoles={['admin']}><CurriculumMapping /></ProtectedRoute>} />
          <Route path="/admin/live-classes" element={<ProtectedRoute allowedRoles={['admin']}><AdminLiveClasses /></ProtectedRoute>} />
          <Route path="/admin/observe/:sessionId" element={<ProtectedRoute allowedRoles={['admin']}><ObserveClass /></ProtectedRoute>} />

          {/* ERP — who may actually see anything is decided by the server, which
              returns 404 for accounts without ERP access. These routes are open
              to any signed-in user so a new role never needs a frontend change. */}
          <Route path="/erp" element={<ProtectedRoute><ErpHome /></ProtectedRoute>} />
          <Route path="/erp/students" element={<ProtectedRoute><ErpStudents /></ProtectedRoute>} />
          <Route path="/erp/staff" element={<ProtectedRoute><ErpStaff /></ProtectedRoute>} />
          <Route path="/erp/classes" element={<ProtectedRoute><ErpClasses /></ProtectedRoute>} />
          <Route path="/erp/access" element={<ProtectedRoute><ErpAccess /></ProtectedRoute>} />
          <Route path="/erp/settings" element={<ProtectedRoute><ErpSettings /></ProtectedRoute>} />

          <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          </Suspense>
        </AuthProvider>
      </BrowserRouter>
    </ThemeProvider>
  );
}
