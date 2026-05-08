import { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { adminAPI } from '../../services/api';
import { Plus, Search, Edit2, Trash2, UserCheck, UserX, X, Loader2, Users, Download, Upload, FileText, CheckCircle } from 'lucide-react';

const ROLES = ['student', 'teacher', 'admin'];
const CLASSES = ['Class 1','Class 2','Class 3','Class 4','Class 5','Class 6','Class 7','Class 8','Class 9','Class 10','Class 11','Class 12'];
const SUBJECTS = ['Mathematics', 'Science', 'English', 'Urdu', 'Islamiat', 'Computer Science', 'Physics', 'Chemistry', 'Biology'];

const ROLE_COLOR = { admin: 'badge-purple', teacher: 'badge-green', student: 'badge-blue' };

export default function ManageUsers() {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [editUser, setEditUser] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [showImportModal, setShowImportModal] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const [form, setForm] = useState({
    name: '', login_id: '', email: '', password: '', role: 'student', class_name: '', subjects: [],
  });

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await adminAPI.getUsers({ role: roleFilter || undefined, search: search || undefined });
      setUsers(data);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, [roleFilter]);

  const setF = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const openCreate = () => {
    setEditUser(null);
    setForm({ name: '', login_id: '', email: '', password: '', role: 'student', class_name: '', subjects: [] });
    setError('');
    setShowModal(true);
  };

  const openEdit = (user) => {
    setEditUser(user);
    setForm({
      name: user.name, login_id: user.login_id, email: user.email || '',
      password: '', role: user.role, class_name: user.class_name || '', subjects: user.subjects || [],
    });
    setError('');
    setShowModal(true);
  };

  const handleSave = async () => {
    if (!form.name || !form.login_id || !form.role) {
      setError('Name, Login ID, and role are required');
      return;
    }
    if (!editUser && !form.password) {
      setError('Password is required for new users');
      return;
    }
    setSaving(true);
    setError('');
    try {
      if (editUser) {
        const { data } = await adminAPI.updateUser(editUser.id, form);
        setUsers((prev) => prev.map((u) => u.id === editUser.id ? data : u));
        setSuccess('User updated successfully');
      } else {
        const { data } = await adminAPI.createUser(form);
        setUsers((prev) => [data, ...prev]);
        setSuccess('User created successfully');
      }
      setShowModal(false);
      setTimeout(() => setSuccess(''), 3000);
    } catch (e) {
      setError(e.response?.data?.error || 'Failed to save user');
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (user) => {
    try {
      const { data } = await adminAPI.updateUser(user.id, { is_active: !user.is_active });
      setUsers((prev) => prev.map((u) => u.id === user.id ? data : u));
    } catch (e) { console.error(e); }
  };

  const deleteUser = async (user) => {
    if (!confirm(`Deactivate ${user.name}?`)) return;
    await adminAPI.deleteUser(user.id);
    setUsers((prev) => prev.map((u) => u.id === user.id ? { ...u, is_active: false } : u));
  };

  const handleImportPDF = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setError('Please select a PDF file');
      return;
    }
    setImporting(true);
    setImportResult(null);
    setError('');
    try {
      const { data } = await adminAPI.importTeachers(file);
      setImportResult(data);
      setSuccess(`${data.created} teacher accounts created successfully!`);
      load(); // Refresh user list
      setTimeout(() => setSuccess(''), 5000);
    } catch (err) {
      setError(err.response?.data?.detail || 'Import failed. Please check the PDF format.');
    } finally {
      setImporting(false);
      e.target.value = ''; // Reset file input
    }
  };

  const handleDownloadCredentials = async () => {
    try {
      const { data } = await adminAPI.downloadCredentials();
      const url = window.URL.createObjectURL(new Blob([data]));
      const a = document.createElement('a');
      a.href = url;
      a.download = 'teacher_credentials.xlsx';
      a.click();
      window.URL.revokeObjectURL(url);
    } catch (err) {
      setError('No credentials file available. Import teachers first.');
    }
  };

  const filtered = users.filter((u) =>
    !search || u.name.toLowerCase().includes(search.toLowerCase()) ||
    u.login_id.toLowerCase().includes(search.toLowerCase())
  );

  return (
    <Layout title="Manage Users">
      {success && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm flex items-center gap-2">
          <UserCheck size={16} /> {success}
        </div>
      )}

      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <div className="relative flex-1">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && load()}
            placeholder="Search by name or ID..."
            className="input-field pl-9"
          />
        </div>
        <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)} className="input-field w-auto">
          <option value="">All Roles</option>
          {ROLES.map((r) => <option key={r} value={r} className="capitalize">{r}</option>)}
        </select>
        <label className={`btn-secondary flex items-center gap-2 whitespace-nowrap cursor-pointer ${importing ? 'opacity-50 pointer-events-none' : ''}`}>
          {importing ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
          {importing ? 'Importing...' : 'Import PDF'}
          <input type="file" accept=".pdf" onChange={handleImportPDF} className="hidden" disabled={importing} />
        </label>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2 whitespace-nowrap">
          <Plus size={16} /> Add User
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 mb-5">
        {[
          { label: 'Students', count: users.filter((u) => u.role === 'student').length, color: 'blue' },
          { label: 'Teachers', count: users.filter((u) => u.role === 'teacher').length, color: 'emerald' },
          { label: 'Admins', count: users.filter((u) => u.role === 'admin').length, color: 'purple' },
        ].map(({ label, count, color }) => (
          <div key={label} className={`card p-3 border-l-4 border-${color}-500`}>
            <div className="text-xl font-bold text-gray-900">{count}</div>
            <div className="text-xs text-gray-500">{label}</div>
          </div>
        ))}
      </div>

      {/* Users Table */}
      <div className="card overflow-hidden p-0">
        {loading ? (
          <div className="p-6 space-y-3">
            {[1,2,3,4,5].map((i) => <div key={i} className="h-14 bg-gray-100 rounded-lg animate-pulse" />)}
          </div>
        ) : filtered.length === 0 ? (
          <div className="text-center py-12">
            <Users size={40} className="mx-auto mb-3 text-gray-300" />
            <p className="text-gray-500">No users found</p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b border-gray-100">
                <tr>
                  <th className="text-left p-4 font-semibold text-gray-600">Name</th>
                  <th className="text-left p-4 font-semibold text-gray-600">Login ID</th>
                  <th className="text-left p-4 font-semibold text-gray-600">Role</th>
                  <th className="text-left p-4 font-semibold text-gray-600 hidden md:table-cell">Class/Subject</th>
                  <th className="text-left p-4 font-semibold text-gray-600">Status</th>
                  <th className="text-right p-4 font-semibold text-gray-600">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {filtered.map((user) => (
                  <tr key={user.id} className="hover:bg-gray-50 transition-colors">
                    <td className="p-4">
                      <div className="flex items-center gap-3">
                        <div className="w-8 h-8 rounded-full bg-blue-100 flex items-center justify-center text-blue-700 text-sm font-bold shrink-0">
                          {user.name.charAt(0).toUpperCase()}
                        </div>
                        <div>
                          <div className="font-medium text-gray-900">{user.name}</div>
                          <div className="text-xs text-gray-400">{user.email || '—'}</div>
                        </div>
                      </div>
                    </td>
                    <td className="p-4 font-mono text-xs text-gray-700">{user.login_id}</td>
                    <td className="p-4">
                      <span className={ROLE_COLOR[user.role] || 'badge-gray'}>{user.role}</span>
                    </td>
                    <td className="p-4 hidden md:table-cell text-gray-500 text-xs">
                      {user.class_name || user.subjects?.slice(0, 2).join(', ') || '—'}
                    </td>
                    <td className="p-4">
                      <span className={user.is_active ? 'badge-green' : 'badge-red'}>
                        {user.is_active ? 'Active' : 'Inactive'}
                      </span>
                    </td>
                    <td className="p-4">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => openEdit(user)} className="p-1.5 rounded hover:bg-gray-100 text-gray-400 hover:text-blue-600">
                          <Edit2 size={14} />
                        </button>
                        <button onClick={() => toggleActive(user)} className={`p-1.5 rounded hover:bg-gray-100 ${user.is_active ? 'text-gray-400 hover:text-red-600' : 'text-gray-400 hover:text-green-600'}`}>
                          {user.is_active ? <UserX size={14} /> : <UserCheck size={14} />}
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Import Result Modal */}
      {importResult && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-lg max-h-[80vh] overflow-hidden flex flex-col">
            <div className="p-5 border-b flex items-center justify-between bg-green-50">
              <div className="flex items-center gap-3">
                <CheckCircle size={24} className="text-green-600" />
                <div>
                  <h2 className="font-bold text-gray-900">Import Complete</h2>
                  <p className="text-sm text-gray-600">{importResult.created} accounts created, {importResult.skipped} skipped</p>
                </div>
              </div>
              <button onClick={() => setImportResult(null)} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
            </div>

            <div className="overflow-y-auto flex-1 p-5">
              {importResult.created_list?.length > 0 && (
                <div className="mb-4">
                  <h3 className="font-semibold text-sm text-gray-700 mb-2">Created Accounts ({importResult.created_list.length})</h3>
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-gray-50">
                          <th className="text-left p-2 font-semibold">#</th>
                          <th className="text-left p-2 font-semibold">Name</th>
                          <th className="text-left p-2 font-semibold">Login ID</th>
                          <th className="text-left p-2 font-semibold">Role</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {importResult.created_list.map((u, i) => (
                          <tr key={i} className="hover:bg-gray-50">
                            <td className="p-2 text-gray-400">{i + 1}</td>
                            <td className="p-2 font-medium">{u.name}</td>
                            <td className="p-2 font-mono text-blue-600">{u.login_id}</td>
                            <td className="p-2"><span className={ROLE_COLOR[u.role] || 'badge-gray'}>{u.role}</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {importResult.skipped_list?.length > 0 && (
                <div className="mb-4">
                  <h3 className="font-semibold text-sm text-orange-700 mb-2">Skipped ({importResult.skipped_list.length})</h3>
                  <div className="space-y-1">
                    {importResult.skipped_list.map((s, i) => (
                      <div key={i} className="text-xs p-2 bg-orange-50 rounded flex justify-between">
                        <span>{s.name}</span>
                        <span className="text-orange-600">{s.reason}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            <div className="p-4 border-t flex gap-3">
              <button onClick={handleDownloadCredentials} className="btn-primary flex-1 flex items-center justify-center gap-2">
                <Download size={16} /> Download Credentials (Excel)
              </button>
              <button onClick={() => setImportResult(null)} className="btn-secondary">Close</button>
            </div>
          </div>
        </div>
      )}

      {/* Create/Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-5 border-b flex items-center justify-between">
              <h2 className="font-bold text-gray-900">{editUser ? 'Edit User' : 'Add New User'}</h2>
              <button onClick={() => setShowModal(false)} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
            </div>
            <div className="p-5 space-y-3">
              {error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>
              )}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Full Name *</label>
                <input type="text" value={form.name} onChange={(e) => setF('name', e.target.value)} className="input-field" placeholder="Enter full name" />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Login ID *</label>
                  <input type="text" value={form.login_id} onChange={(e) => setF('login_id', e.target.value)} className="input-field" placeholder="e.g. STU001" disabled={!!editUser} />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Role *</label>
                  <select value={form.role} onChange={(e) => setF('role', e.target.value)} className="input-field capitalize">
                    {ROLES.map((r) => <option key={r} value={r} className="capitalize">{r}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Password {editUser ? '(leave blank to keep)' : '*'}</label>
                <input type="password" value={form.password} onChange={(e) => setF('password', e.target.value)} className="input-field" placeholder={editUser ? 'New password (optional)' : 'Set password'} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Email</label>
                <input type="email" value={form.email} onChange={(e) => setF('email', e.target.value)} className="input-field" placeholder="Optional email" />
              </div>
              {form.role === 'student' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Class</label>
                  <select value={form.class_name} onChange={(e) => setF('class_name', e.target.value)} className="input-field">
                    <option value="">Select class</option>
                    {CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              )}
              {form.role === 'teacher' && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Subjects</label>
                  <div className="grid grid-cols-2 gap-1.5">
                    {SUBJECTS.map((s) => (
                      <label key={s} className="flex items-center gap-2 text-xs cursor-pointer">
                        <input
                          type="checkbox"
                          checked={form.subjects.includes(s)}
                          onChange={(e) => {
                            const subs = e.target.checked
                              ? [...form.subjects, s]
                              : form.subjects.filter((x) => x !== s);
                            setF('subjects', subs);
                          }}
                          className="rounded"
                        />
                        {s}
                      </label>
                    ))}
                  </div>
                </div>
              )}
              <div className="flex gap-3 pt-2">
                <button onClick={() => setShowModal(false)} className="btn-secondary flex-1">Cancel</button>
                <button onClick={handleSave} disabled={saving} className="btn-primary flex-1 flex items-center justify-center gap-2">
                  {saving ? <Loader2 size={16} className="animate-spin" /> : null}
                  {editUser ? 'Update' : 'Create'} User
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
