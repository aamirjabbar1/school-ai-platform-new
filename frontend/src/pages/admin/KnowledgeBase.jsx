import { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { documentAPI } from '../../services/api';
import { Upload, Database, Trash2, RefreshCw, CheckCircle, AlertCircle, Loader2, X, FileText, BookOpen, Filter } from 'lucide-react';

const SUBJECTS = ['Mathematics', 'Science', 'English', 'Urdu', 'Islamiat', 'Computer Science', 'Physics', 'Chemistry', 'Biology', 'Social Studies', 'History', 'Geography', 'Other'];
const CLASS_LEVELS = ['All Classes', 'Class 1', 'Class 2', 'Class 3', 'Class 4', 'Class 5', 'Class 6', 'Class 7', 'Class 8', 'Class 9', 'Class 10', 'Class 11', 'Class 12'];

export default function KnowledgeBase() {
  const [documents, setDocuments] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [showUpload, setShowUpload] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [filterSubject, setFilterSubject] = useState('');
  const [filterClass, setFilterClass] = useState('');

  const [uploadForm, setUploadForm] = useState({
    title: '', subject: '', class_level: 'All Classes', description: '', file: null,
  });

  const loadData = async () => {
    setLoading(true);
    try {
      const [{ data: docs }, { data: st }] = await Promise.all([
        documentAPI.getAll({ subject: filterSubject || undefined, class_level: filterClass || undefined }),
        documentAPI.getStats(),
      ]);
      setDocuments(docs);
      setStats(st);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [filterSubject, filterClass]);

  const setUF = (k, v) => setUploadForm((f) => ({ ...f, [k]: v }));

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!uploadForm.file || !uploadForm.title || !uploadForm.subject || !uploadForm.class_level) {
      setError('All fields and a file are required');
      return;
    }
    setUploading(true);
    setError('');
    try {
      const fd = new FormData();
      fd.append('document', uploadForm.file);
      fd.append('title', uploadForm.title);
      fd.append('subject', uploadForm.subject);
      fd.append('class_level', uploadForm.class_level);
      fd.append('description', uploadForm.description);

      const { data } = await documentAPI.upload(fd);
      setDocuments((prev) => [data, ...prev]);
      setSuccess(`"${uploadForm.title}" uploaded. AI ingestion started...`);
      setShowUpload(false);
      setUploadForm({ title: '', subject: '', class_level: 'All Classes', description: '', file: null });
      setTimeout(() => { setSuccess(''); loadData(); }, 4000);
    } catch (e) {
      setError(e.response?.data?.error || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const reingest = async (id, title) => {
    try {
      await documentAPI.reingest(id);
      setSuccess(`Re-ingestion started for "${title}"`);
      setTimeout(() => { setSuccess(''); loadData(); }, 4000);
    } catch (e) {
      setError('Re-ingestion failed');
    }
  };

  const deleteDoc = async (id, title) => {
    if (!confirm(`Delete "${title}" and all its content chunks? This cannot be undone.`)) return;
    try {
      await documentAPI.delete(id);
      setDocuments((prev) => prev.filter((d) => d.id !== id));
      setSuccess('Document deleted');
      setTimeout(() => setSuccess(''), 3000);
    } catch (e) {
      setError('Delete failed');
    }
  };

  const formatSize = (bytes) => {
    if (!bytes) return '—';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  return (
    <Layout title="Knowledge Base">
      {success && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm flex items-center gap-2">
          <CheckCircle size={16} /> {success}
        </div>
      )}
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-center gap-2">
          <AlertCircle size={16} /> {error}
          <button onClick={() => setError('')} className="ml-auto"><X size={14} /></button>
        </div>
      )}

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-5">
          {[
            { label: 'Total Books', value: stats.total_documents, icon: BookOpen, color: 'blue' },
            { label: 'Ingested', value: stats.ingested_documents, icon: CheckCircle, color: 'green' },
            { label: 'AI Chunks', value: parseInt(stats.total_chunks || 0).toLocaleString(), icon: Database, color: 'purple' },
            { label: 'Subjects', value: stats.subjects_covered, icon: Filter, color: 'orange' },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="card p-4">
              <div className={`w-9 h-9 rounded-lg bg-${color}-100 flex items-center justify-center mb-2`}>
                <Icon size={18} className={`text-${color}-600`} />
              </div>
              <div className="text-xl font-bold text-gray-900">{value}</div>
              <div className="text-xs text-gray-500">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <select value={filterSubject} onChange={(e) => setFilterSubject(e.target.value)} className="input-field w-auto">
          <option value="">All Subjects</option>
          {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filterClass} onChange={(e) => setFilterClass(e.target.value)} className="input-field w-auto">
          <option value="">All Classes</option>
          {CLASS_LEVELS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button onClick={() => setShowUpload(true)} className="btn-primary flex items-center gap-2 ml-auto">
          <Upload size={16} /> Upload Book / Material
        </button>
      </div>

      {/* Info Banner */}
      <div className="p-4 bg-blue-50 rounded-xl border border-blue-200 mb-5 text-sm text-blue-800">
        <p className="font-semibold mb-1">📚 How the Knowledge Base Works</p>
        <p>Upload school textbooks and curriculum materials (PDF, DOCX, TXT). The AI automatically processes and indexes them. The AI chatbot will ONLY answer questions based on this uploaded content — no external internet knowledge.</p>
      </div>

      {/* Documents List */}
      {loading ? (
        <div className="grid gap-3">{[1,2,3,4].map((i) => <div key={i} className="h-20 bg-gray-100 rounded-xl animate-pulse" />)}</div>
      ) : documents.length === 0 ? (
        <div className="card text-center py-16">
          <Database size={48} className="mx-auto mb-4 text-gray-200" />
          <h3 className="font-semibold text-gray-600 mb-1">Knowledge Base is Empty</h3>
          <p className="text-sm text-gray-400 mb-4">Upload school books and curriculum materials to enable AI assistance</p>
          <button onClick={() => setShowUpload(true)} className="btn-primary inline-flex items-center gap-2">
            <Upload size={16} /> Upload First Document
          </button>
        </div>
      ) : (
        <div className="grid gap-3">
          {documents.map((doc) => (
            <div key={doc.id} className="card hover:shadow-md transition-shadow">
              <div className="flex items-start gap-4">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0
                  ${doc.is_ingested ? 'bg-green-100 text-green-600' : 'bg-yellow-100 text-yellow-600'}`}>
                  <FileText size={20} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-semibold text-gray-800">{doc.title}</h3>
                    <span className="badge-blue">{doc.subject}</span>
                    <span className="badge-purple">{doc.class_level}</span>
                    {doc.is_ingested ? (
                      <span className="badge-green">
                        <CheckCircle size={10} className="mr-1" /> {doc.total_chunks} chunks
                      </span>
                    ) : doc.ingestion_error ? (
                      <span className="badge-red">
                        <AlertCircle size={10} className="mr-1" /> Failed
                      </span>
                    ) : (
                      <span className="badge-yellow">
                        <Loader2 size={10} className="animate-spin mr-1" /> Processing
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-400 mt-1">
                    {doc.file_name} • {formatSize(doc.file_size)} • {doc.file_type.toUpperCase()}
                    {doc.ingestion_error && (
                      <span className="text-red-500 ml-2">Error: {doc.ingestion_error}</span>
                    )}
                  </div>
                  <div className="text-xs text-gray-400">
                    Uploaded {(() => { const d = new Date((doc.created_at || '').replace(/(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+([+-])/, '$1$2')); return isNaN(d) ? '' : d.toLocaleDateString(); })()}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {(!doc.is_ingested || doc.ingestion_error) && (
                    <button
                      onClick={() => reingest(doc.id, doc.title)}
                      className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-blue-600"
                      title="Re-process"
                    >
                      <RefreshCw size={15} />
                    </button>
                  )}
                  <button
                    onClick={() => deleteDoc(doc.id, doc.title)}
                    className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-red-600"
                    title="Delete"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Upload Modal */}
      {showUpload && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-5 border-b flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Upload size={18} className="text-blue-600" />
                <h2 className="font-bold text-gray-900">Upload Document</h2>
              </div>
              <button onClick={() => setShowUpload(false)} className="text-gray-400 hover:text-gray-600"><X size={20} /></button>
            </div>
            <form onSubmit={handleUpload} className="p-5 space-y-4">
              {error && <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Book / Document Title *</label>
                <input type="text" value={uploadForm.title} onChange={(e) => setUF('title', e.target.value)} className="input-field" placeholder="e.g. Class 9 Chemistry Textbook" required />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Subject *</label>
                  <select value={uploadForm.subject} onChange={(e) => setUF('subject', e.target.value)} className="input-field" required>
                    <option value="">Select</option>
                    {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Class Level *</label>
                  <select value={uploadForm.class_level} onChange={(e) => setUF('class_level', e.target.value)} className="input-field" required>
                    {CLASS_LEVELS.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                <input type="text" value={uploadForm.description} onChange={(e) => setUF('description', e.target.value)} className="input-field" placeholder="Brief description (optional)" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">File * (PDF, DOCX, TXT)</label>
                <input
                  type="file"
                  accept=".pdf,.docx,.doc,.txt"
                  onChange={(e) => setUF('file', e.target.files[0])}
                  className="w-full text-sm text-gray-500 file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-gray-200 file:text-sm file:bg-gray-50 hover:file:bg-gray-100"
                  required
                />
                <p className="text-xs text-gray-400 mt-1">Max size: 50MB</p>
              </div>
              <div className="flex gap-3 pt-1">
                <button type="button" onClick={() => setShowUpload(false)} className="btn-secondary flex-1">Cancel</button>
                <button type="submit" disabled={uploading} className="btn-primary flex-1 flex items-center justify-center gap-2">
                  {uploading ? <><Loader2 size={16} className="animate-spin" /> Uploading...</> : <><Upload size={16} /> Upload & Process</>}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </Layout>
  );
}
