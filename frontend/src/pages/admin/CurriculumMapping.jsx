import { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { adminAPI } from '../../services/api';
import {
  Plus, Edit2, Trash2, X, Loader2, ArrowRight, GraduationCap,
  CheckCircle, AlertCircle, Info, ToggleLeft, ToggleRight,
} from 'lucide-react';

// Classes a student can be enrolled in (the "source" of a mapping).
const STUDENT_CLASSES = [
  'Pre-Nursery', 'Nursery', 'KG',
  'Class 1', 'Class 2', 'Class 3', 'Class 4', 'Class 5', 'Class 6',
  'Class 7', 'Class 8', 'Class 9', 'Class 10', 'Class 11', 'Class 12',
];
// Classes the knowledge base stores content under (the "target" of a mapping).
const KB_CLASSES = [
  'Class 1', 'Class 2', 'Class 3', 'Class 4', 'Class 5', 'Class 6',
  'Class 7', 'Class 8', 'Class 9', 'Class 10', 'Class 11', 'Class 12',
];

export default function CurriculumMapping() {
  const [mappings, setMappings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showModal, setShowModal] = useState(false);
  const [editMapping, setEditMapping] = useState(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [form, setForm] = useState({ source_class: '', target_class: '', is_active: true });

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await adminAPI.getCurriculumMappings();
      setMappings(data);
    } catch (e) {
      setError('Failed to load mappings');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const setF = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const openCreate = () => {
    setEditMapping(null);
    setForm({ source_class: '', target_class: '', is_active: true });
    setError('');
    setShowModal(true);
  };

  const openEdit = (m) => {
    setEditMapping(m);
    setForm({ source_class: m.source_class, target_class: m.target_class, is_active: m.is_active });
    setError('');
    setShowModal(true);
  };

  const flash = (msg) => { setSuccess(msg); setTimeout(() => setSuccess(''), 3000); };

  const handleSave = async () => {
    if (!form.source_class || !form.target_class) {
      setError('Both source and target class are required');
      return;
    }
    if (form.source_class === form.target_class) {
      setError('Source and target class must be different');
      return;
    }
    setSaving(true);
    setError('');
    try {
      if (editMapping) {
        const { data } = await adminAPI.updateCurriculumMapping(editMapping.id, form);
        setMappings((prev) => prev.map((m) => m.id === editMapping.id ? data : m));
        flash('Mapping updated');
      } else {
        const { data } = await adminAPI.createCurriculumMapping(form);
        setMappings((prev) => [...prev, data].sort((a, b) => a.source_class.localeCompare(b.source_class)));
        flash('Mapping created');
      }
      setShowModal(false);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to save mapping');
    } finally {
      setSaving(false);
    }
  };

  const toggleActive = async (m) => {
    try {
      const { data } = await adminAPI.updateCurriculumMapping(m.id, { is_active: !m.is_active });
      setMappings((prev) => prev.map((x) => x.id === m.id ? data : x));
    } catch (e) {
      setError('Failed to update mapping');
    }
  };

  const remove = async (m) => {
    if (!confirm(`Delete the mapping ${m.source_class} → ${m.target_class}?`)) return;
    try {
      await adminAPI.deleteCurriculumMapping(m.id);
      setMappings((prev) => prev.filter((x) => x.id !== m.id));
      flash('Mapping deleted');
    } catch (e) {
      setError('Failed to delete mapping');
    }
  };

  return (
    <Layout title="Academic Settings">
      {success && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm flex items-center gap-2">
          <CheckCircle size={16} /> {success}
        </div>
      )}
      {error && !showModal && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-center gap-2">
          <AlertCircle size={16} /> {error}
          <button onClick={() => setError('')} className="ml-auto"><X size={14} /></button>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-2">
          <GraduationCap size={20} className="text-brand-purple" />
          <h2 className="font-bold text-ink text-lg">Curriculum Mapping</h2>
        </div>
        <button onClick={openCreate} className="btn-primary flex items-center gap-2">
          <Plus size={16} /> Add Mapping
        </button>
      </div>

      {/* Info banner */}
      <div className="p-4 bg-blue-50 rounded-xl border border-blue-200 mb-5 text-sm text-blue-800">
        <p className="font-semibold mb-1 flex items-center gap-1.5"><Info size={15} /> How Curriculum Mapping Works</p>
        <p>
          Some classes follow a Pre-Board structure where students study a higher class's curriculum
          (e.g. <strong>Class 8 students study the Class 9 curriculum</strong>). Add a mapping so the
          chatbot automatically searches the mapped class's books and study material — students never
          need to mention the curriculum class in their questions. Knowledge base content is not duplicated.
        </p>
      </div>

      {/* Mappings list */}
      <div className="card overflow-hidden p-0">
        {loading ? (
          <div className="p-6 space-y-3">
            {[1, 2, 3].map((i) => <div key={i} className="h-14 bg-surface-3 rounded-lg animate-pulse" />)}
          </div>
        ) : mappings.length === 0 ? (
          <div className="text-center py-14">
            <GraduationCap size={40} className="mx-auto mb-3 text-faint" />
            <p className="text-muted mb-1">No curriculum mappings yet</p>
            <p className="text-sm text-faint mb-4">Add one to route a class to a different curriculum.</p>
            <button onClick={openCreate} className="btn-primary inline-flex items-center gap-2">
              <Plus size={16} /> Add Mapping
            </button>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-3/60 border-b border-line">
                <tr>
                  <th className="text-left p-4 font-semibold text-muted">Student Class</th>
                  <th className="text-left p-4 font-semibold text-muted">Knowledge Base Class</th>
                  <th className="text-left p-4 font-semibold text-muted">Status</th>
                  <th className="text-right p-4 font-semibold text-muted">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {mappings.map((m) => (
                  <tr key={m.id} className="hover:bg-surface-3/60 transition-colors">
                    <td className="p-4">
                      <span className="badge-blue">{m.source_class}</span>
                    </td>
                    <td className="p-4">
                      <span className="inline-flex items-center gap-2 text-muted">
                        <ArrowRight size={14} className="text-faint" />
                        <span className="badge-purple">{m.target_class}</span>
                      </span>
                    </td>
                    <td className="p-4">
                      <button
                        onClick={() => toggleActive(m)}
                        className="inline-flex items-center gap-1.5"
                        title={m.is_active ? 'Active — click to disable' : 'Inactive — click to enable'}
                      >
                        {m.is_active
                          ? <><ToggleRight size={18} className="text-green-600" /> <span className="badge-green">Active</span></>
                          : <><ToggleLeft size={18} className="text-faint" /> <span className="badge-gray">Inactive</span></>}
                      </button>
                    </td>
                    <td className="p-4">
                      <div className="flex items-center justify-end gap-1">
                        <button onClick={() => openEdit(m)} className="p-1.5 rounded hover:bg-surface-3 text-faint hover:text-blue-600" title="Edit">
                          <Edit2 size={14} />
                        </button>
                        <button onClick={() => remove(m)} className="p-1.5 rounded hover:bg-surface-3 text-faint hover:text-red-600" title="Delete">
                          <Trash2 size={14} />
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

      {/* Create / Edit Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-surface rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-5 border-b flex items-center justify-between">
              <h2 className="font-bold text-ink">{editMapping ? 'Edit Mapping' : 'Add Curriculum Mapping'}</h2>
              <button onClick={() => setShowModal(false)} className="text-faint hover:text-muted"><X size={20} /></button>
            </div>
            <div className="p-5 space-y-4">
              {error && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>
              )}
              <div>
                <label className="block text-sm font-medium text-ink/90 mb-1">Student Class (Source) *</label>
                <select value={form.source_class} onChange={(e) => setF('source_class', e.target.value)} className="input-field">
                  <option value="">Select student class</option>
                  {STUDENT_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <p className="text-xs text-faint mt-1">The class students are actually enrolled in.</p>
              </div>
              <div className="flex justify-center text-faint"><ArrowRight size={18} /></div>
              <div>
                <label className="block text-sm font-medium text-ink/90 mb-1">Knowledge Base Class (Target) *</label>
                <select value={form.target_class} onChange={(e) => setF('target_class', e.target.value)} className="input-field">
                  <option value="">Select knowledge base class</option>
                  {KB_CLASSES.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
                <p className="text-xs text-faint mt-1">The curriculum class whose content should be searched.</p>
              </div>
              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={form.is_active} onChange={(e) => setF('is_active', e.target.checked)} className="rounded" />
                Active
              </label>
              <div className="flex gap-3 pt-1">
                <button onClick={() => setShowModal(false)} className="btn-secondary flex-1">Cancel</button>
                <button onClick={handleSave} disabled={saving} className="btn-primary flex-1 flex items-center justify-center gap-2">
                  {saving ? <Loader2 size={16} className="animate-spin" /> : null}
                  {editMapping ? 'Update' : 'Create'} Mapping
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </Layout>
  );
}
