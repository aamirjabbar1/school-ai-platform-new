import { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { documentAPI } from '../../services/api';
import {
  Upload, Database, Trash2, RefreshCw, CheckCircle, AlertCircle, Loader2, X,
  FileText, BookOpen, Filter, ScrollText, ChevronRight,
} from 'lucide-react';

const SUBJECTS = ['Mathematics', 'Science', 'English', 'Urdu', 'Islamiat', 'Computer Science', 'Physics', 'Chemistry', 'Biology', 'Social Studies', 'History', 'Geography', 'Other'];
const CLASS_LEVELS = ['All Classes', 'Class 1', 'Class 2', 'Class 3', 'Class 4', 'Class 5', 'Class 6', 'Class 7', 'Class 8', 'Class 9', 'Class 10', 'Class 11', 'Class 12'];
const LANGUAGES = ['English', 'Urdu', 'Bilingual'];
const PAPER_TYPES = [
  { value: 'past_paper', label: 'Past Paper' },
  { value: 'test',       label: 'Test Paper' },
  { value: 'midterm',    label: 'Midterm Paper' },
  { value: 'final',      label: 'Final Exam Paper' },
  { value: 'mcqs',       label: 'MCQs Sheet' },
];
const PAPER_TYPE_LABEL = Object.fromEntries(PAPER_TYPES.map((p) => [p.value, p.label]));
const CURRENT_YEAR = new Date().getFullYear();
const YEARS = Array.from({ length: 15 }, (_, i) => String(CURRENT_YEAR - i));

const ACCEPT = '.pdf,.docx,.doc,.txt';

// Literal class strings so Tailwind's static scan generates them (no runtime concatenation).
const STAT_STYLES = {
  blue:   { wrap: 'bg-blue-100',   icon: 'text-blue-600' },
  purple: { wrap: 'bg-purple-100', icon: 'text-purple-600' },
  green:  { wrap: 'bg-green-100',  icon: 'text-green-600' },
  orange: { wrap: 'bg-orange-100', icon: 'text-orange-600' },
};

export default function KnowledgeBase() {
  const [documents, setDocuments] = useState([]);
  const [stats, setStats] = useState(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [showTypeSelect, setShowTypeSelect] = useState(false);
  const [showUpload, setShowUpload] = useState(false);       // book modal
  const [showPaperUpload, setShowPaperUpload] = useState(false); // question paper modal
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [filterSubject, setFilterSubject] = useState('');
  const [filterClass, setFilterClass] = useState('');
  const [filterType, setFilterType] = useState(''); // '' | 'book' | 'exam'

  const [uploadForm, setUploadForm] = useState({
    title: '', subject: '', class_level: 'All Classes', description: '', file: null,
  });
  const [paperForm, setPaperForm] = useState({
    title: '', subject: '', class_level: 'All Classes', paper_type: 'past_paper',
    academic_year: String(CURRENT_YEAR), chapter: '', language: 'English', file: null,
  });

  const loadData = async () => {
    setLoading(true);
    try {
      const [{ data: docs }, { data: st }] = await Promise.all([
        documentAPI.getAll({
          subject: filterSubject || undefined,
          class_level: filterClass || undefined,
          document_type: filterType || undefined,
        }),
        documentAPI.getStats(),
      ]);
      setDocuments(docs);
      setStats(st);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { loadData(); }, [filterSubject, filterClass, filterType]);

  const setUF = (k, v) => setUploadForm((f) => ({ ...f, [k]: v }));
  const setPF = (k, v) => setPaperForm((f) => ({ ...f, [k]: v }));

  const onProgress = (e) => setUploadProgress(Math.round((e.loaded / (e.total || 1)) * 100));

  // ── Book / study material upload (unchanged behaviour) ──────────────────────
  const handleUpload = async (e) => {
    e.preventDefault();
    if (!uploadForm.file || !uploadForm.title || !uploadForm.subject || !uploadForm.class_level) {
      setError('All fields and a file are required');
      return;
    }
    setUploading(true);
    setUploadProgress(0);
    setError('');
    try {
      const fd = new FormData();
      fd.append('document', uploadForm.file);
      fd.append('title', uploadForm.title);
      fd.append('subject', uploadForm.subject);
      fd.append('class_level', uploadForm.class_level);
      fd.append('description', uploadForm.description);
      fd.append('document_type', 'book');

      const { data } = await documentAPI.upload(fd, onProgress);
      setDocuments((prev) => [data, ...prev]);
      setSuccess(`"${uploadForm.title}" uploaded. AI ingestion started...`);
      setShowUpload(false);
      setUploadForm({ title: '', subject: '', class_level: 'All Classes', description: '', file: null });
      setTimeout(() => { setSuccess(''); loadData(); }, 4000);
    } catch (e) {
      setError(e.response?.data?.detail || e.response?.data?.error || 'Upload failed');
    } finally {
      setUploading(false);
      setUploadProgress(0);
    }
  };

  // ── Question paper / past paper upload ──────────────────────────────────────
  const handlePaperUpload = async (e) => {
    e.preventDefault();
    if (!paperForm.file || !paperForm.title || !paperForm.subject || !paperForm.class_level || !paperForm.paper_type) {
      setError('Title, subject, class, paper type and a file are required');
      return;
    }
    setUploading(true);
    setUploadProgress(0);
    setError('');
    try {
      const fd = new FormData();
      fd.append('document', paperForm.file);
      fd.append('title', paperForm.title);
      fd.append('subject', paperForm.subject);
      fd.append('class_level', paperForm.class_level);
      fd.append('document_type', 'exam');
      fd.append('paper_type', paperForm.paper_type);
      fd.append('academic_year', paperForm.academic_year);
      fd.append('chapter', paperForm.chapter);
      fd.append('language', paperForm.language);

      const { data } = await documentAPI.upload(fd, onProgress);
      setDocuments((prev) => [data, ...prev]);
      setSuccess(`Question paper "${paperForm.title}" uploaded. AI ingestion started...`);
      setShowPaperUpload(false);
      setPaperForm({ title: '', subject: '', class_level: 'All Classes', paper_type: 'past_paper', academic_year: String(CURRENT_YEAR), chapter: '', language: 'English', file: null });
      setTimeout(() => { setSuccess(''); loadData(); }, 4000);
    } catch (e) {
      setError(e.response?.data?.detail || e.response?.data?.error || 'Upload failed');
    } finally {
      setUploading(false);
      setUploadProgress(0);
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
      setSuccess('Deleted');
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

  const ProgressBar = () => (
    <div className="space-y-1">
      <div className="w-full bg-surface-3 rounded-full h-2 overflow-hidden">
        <div className="bg-blue-600 h-2 transition-all duration-200" style={{ width: `${uploadProgress}%` }} />
      </div>
      <p className="text-xs text-muted text-center">
        {uploadProgress < 100 ? `Uploading… ${uploadProgress}%` : 'Processing on server…'}
      </p>
    </div>
  );

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
            { label: 'Books / Material', value: stats.books ?? stats.total_documents, icon: BookOpen, color: 'blue' },
            { label: 'Question Papers', value: stats.question_papers ?? 0, icon: ScrollText, color: 'purple' },
            { label: 'AI Chunks', value: parseInt(stats.total_chunks || 0).toLocaleString(), icon: Database, color: 'green' },
            { label: 'Subjects', value: stats.subjects_covered, icon: Filter, color: 'orange' },
          ].map(({ label, value, icon: Icon, color }) => (
            <div key={label} className="card p-4">
              <div className={`w-9 h-9 rounded-lg ${STAT_STYLES[color].wrap} flex items-center justify-center mb-2`}>
                <Icon size={18} className={STAT_STYLES[color].icon} />
              </div>
              <div className="text-xl font-bold text-ink">{value}</div>
              <div className="text-xs text-muted">{label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Controls */}
      <div className="flex flex-col sm:flex-row gap-3 mb-5">
        <select value={filterType} onChange={(e) => setFilterType(e.target.value)} className="input-field w-auto">
          <option value="">All Content</option>
          <option value="book">Books / Material</option>
          <option value="exam">Question Papers</option>
        </select>
        <select value={filterSubject} onChange={(e) => setFilterSubject(e.target.value)} className="input-field w-auto">
          <option value="">All Subjects</option>
          {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <select value={filterClass} onChange={(e) => setFilterClass(e.target.value)} className="input-field w-auto">
          <option value="">All Classes</option>
          {CLASS_LEVELS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <button onClick={() => setShowTypeSelect(true)} className="btn-primary flex items-center gap-2 ml-auto">
          <Upload size={16} /> Upload to Knowledge Base
        </button>
      </div>

      {/* Info Banner */}
      <div className="p-4 bg-blue-50 rounded-xl border border-blue-200 mb-5 text-sm text-blue-800">
        <p className="font-semibold mb-1">📚 How the Knowledge Base Works</p>
        <p>Upload textbooks &amp; study material and past / question papers (PDF, DOCX, TXT). The AI processes and indexes them. The chatbot answers students from this content, and the AI uses past papers to generate model papers, practice tests, and important-question predictions.</p>
      </div>

      {/* Documents List */}
      {loading ? (
        <div className="grid gap-3">{[1,2,3,4].map((i) => <div key={i} className="h-20 bg-surface-3 rounded-xl animate-pulse" />)}</div>
      ) : documents.length === 0 ? (
        <div className="card text-center py-16">
          <Database size={48} className="mx-auto mb-4 text-gray-200" />
          <h3 className="font-semibold text-muted mb-1">Nothing here yet</h3>
          <p className="text-sm text-faint mb-4">Upload books, study material, or past papers to power the AI</p>
          <button onClick={() => setShowTypeSelect(true)} className="btn-primary inline-flex items-center gap-2">
            <Upload size={16} /> Upload to Knowledge Base
          </button>
        </div>
      ) : (
        <div className="grid gap-3">
          {documents.map((doc) => {
            const isExam = doc.document_type === 'exam';
            return (
            <div key={doc.id} className="card hover:shadow-md transition-shadow">
              <div className="flex items-start gap-4">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0
                  ${doc.is_ingested
                    ? (isExam ? 'bg-purple-100 text-purple-600' : 'bg-green-100 text-green-600')
                    : 'bg-yellow-100 text-yellow-600'}`}>
                  {isExam ? <ScrollText size={20} /> : <BookOpen size={20} />}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="font-semibold text-ink">{doc.title}</h3>
                    {isExam
                      ? <span className="badge-purple">{PAPER_TYPE_LABEL[doc.paper_type] || 'Question Paper'}</span>
                      : <span className="badge-gray">Book / Material</span>}
                    <span className="badge-blue">{doc.subject}</span>
                    <span className="badge-purple">{doc.class_level}</span>
                    {isExam && doc.academic_year && <span className="badge-gray">{doc.academic_year}</span>}
                    {isExam && doc.chapter && <span className="badge-gray">{doc.chapter}</span>}
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
                  <div className="text-xs text-faint mt-1">
                    {doc.file_name} • {formatSize(doc.file_size)} • {doc.file_type.toUpperCase()}
                    {doc.language && doc.language !== 'English' && ` • ${doc.language}`}
                    {doc.ingestion_error && (
                      <span className="text-red-500 ml-2">Error: {doc.ingestion_error}</span>
                    )}
                  </div>
                  <div className="text-xs text-faint">
                    Uploaded {(() => { const d = new Date((doc.created_at || '').replace(/(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+([+-])/, '$1$2')); return isNaN(d) ? '' : d.toLocaleDateString(); })()}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {(!doc.is_ingested || doc.ingestion_error) && (
                    <button
                      onClick={() => reingest(doc.id, doc.title)}
                      className="p-1.5 rounded-lg hover:bg-surface-3 text-faint hover:text-blue-600"
                      title="Re-process"
                    >
                      <RefreshCw size={15} />
                    </button>
                  )}
                  <button
                    onClick={() => deleteDoc(doc.id, doc.title)}
                    className="p-1.5 rounded-lg hover:bg-surface-3 text-faint hover:text-red-600"
                    title="Delete"
                  >
                    <Trash2 size={15} />
                  </button>
                </div>
              </div>
            </div>
            );
          })}
        </div>
      )}

      {/* Type Selection Modal */}
      {showTypeSelect && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-surface rounded-2xl shadow-xl w-full max-w-lg">
            <div className="p-5 border-b flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Upload size={18} className="text-blue-600" />
                <h2 className="font-bold text-ink">What would you like to upload?</h2>
              </div>
              <button onClick={() => setShowTypeSelect(false)} className="text-faint hover:text-muted"><X size={20} /></button>
            </div>
            <div className="p-5 grid sm:grid-cols-2 gap-4">
              <button
                onClick={() => { setShowTypeSelect(false); setError(''); setShowUpload(true); }}
                className="text-left p-5 rounded-xl border-2 border-line hover:border-blue-400 hover:bg-blue-50/40 transition-all group"
              >
                <div className="w-11 h-11 rounded-xl bg-blue-100 text-blue-600 flex items-center justify-center mb-3">
                  <BookOpen size={22} />
                </div>
                <div className="font-semibold text-ink flex items-center gap-1">
                  Book / Study Material <ChevronRight size={15} className="text-faint group-hover:text-blue-500" />
                </div>
                <p className="text-xs text-muted mt-1">Textbooks, notes and curriculum material for the AI chatbot.</p>
              </button>
              <button
                onClick={() => { setShowTypeSelect(false); setError(''); setShowPaperUpload(true); }}
                className="text-left p-5 rounded-xl border-2 border-line hover:border-purple-400 hover:bg-purple-50/40 transition-all group"
              >
                <div className="w-11 h-11 rounded-xl bg-purple-100 text-purple-600 flex items-center justify-center mb-3">
                  <ScrollText size={22} />
                </div>
                <div className="font-semibold text-ink flex items-center gap-1">
                  Question Paper / Past Papers <ChevronRight size={15} className="text-faint group-hover:text-purple-500" />
                </div>
                <p className="text-xs text-muted mt-1">Past, test, midterm, final &amp; MCQ papers the AI uses to generate &amp; predict.</p>
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Book Upload Modal */}
      {showUpload && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-surface rounded-2xl shadow-xl w-full max-w-md">
            <div className="p-5 border-b flex items-center justify-between">
              <div className="flex items-center gap-2">
                <BookOpen size={18} className="text-blue-600" />
                <h2 className="font-bold text-ink">Upload Book / Study Material</h2>
              </div>
              <button onClick={() => setShowUpload(false)} className="text-faint hover:text-muted"><X size={20} /></button>
            </div>
            <form onSubmit={handleUpload} className="p-5 space-y-4">
              {error && <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>}
              <div>
                <label className="block text-sm font-medium text-ink/90 mb-1">Book / Document Title *</label>
                <input type="text" value={uploadForm.title} onChange={(e) => setUF('title', e.target.value)} className="input-field" placeholder="e.g. Class 9 Chemistry Textbook" required />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-ink/90 mb-1">Subject *</label>
                  <select value={uploadForm.subject} onChange={(e) => setUF('subject', e.target.value)} className="input-field" required>
                    <option value="">Select</option>
                    {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink/90 mb-1">Class Level *</label>
                  <select value={uploadForm.class_level} onChange={(e) => setUF('class_level', e.target.value)} className="input-field" required>
                    {CLASS_LEVELS.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-ink/90 mb-1">Description</label>
                <input type="text" value={uploadForm.description} onChange={(e) => setUF('description', e.target.value)} className="input-field" placeholder="Brief description (optional)" />
              </div>
              <div>
                <label className="block text-sm font-medium text-ink/90 mb-1">File * (PDF, DOCX, TXT)</label>
                <input
                  type="file"
                  accept={ACCEPT}
                  onChange={(e) => setUF('file', e.target.files[0])}
                  className="w-full text-sm text-muted file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-line file:text-sm file:bg-surface-3/60 hover:file:bg-surface-3"
                  required
                />
                <p className="text-xs text-faint mt-1">Max size: 50MB</p>
              </div>
              {uploading && <ProgressBar />}
              <div className="flex gap-3 pt-1">
                <button type="button" onClick={() => setShowUpload(false)} className="btn-secondary flex-1" disabled={uploading}>Cancel</button>
                <button type="submit" disabled={uploading} className="btn-primary flex-1 flex items-center justify-center gap-2">
                  {uploading ? <><Loader2 size={16} className="animate-spin" /> Uploading...</> : <><Upload size={16} /> Upload & Process</>}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Question Paper Upload Modal */}
      {showPaperUpload && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4 overflow-y-auto">
          <div className="bg-surface rounded-2xl shadow-xl w-full max-w-md my-4">
            <div className="p-5 border-b flex items-center justify-between">
              <div className="flex items-center gap-2">
                <ScrollText size={18} className="text-purple-600" />
                <h2 className="font-bold text-ink">Upload Question Paper / Past Paper</h2>
              </div>
              <button onClick={() => setShowPaperUpload(false)} className="text-faint hover:text-muted"><X size={20} /></button>
            </div>
            <form onSubmit={handlePaperUpload} className="p-5 space-y-4">
              {error && <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>}
              <div>
                <label className="block text-sm font-medium text-ink/90 mb-1">Paper Title *</label>
                <input type="text" value={paperForm.title} onChange={(e) => setPF('title', e.target.value)} className="input-field" placeholder="e.g. Class 10 Physics Final Exam 2023" required />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-ink/90 mb-1">Subject *</label>
                  <select value={paperForm.subject} onChange={(e) => setPF('subject', e.target.value)} className="input-field" required>
                    <option value="">Select</option>
                    {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink/90 mb-1">Class *</label>
                  <select value={paperForm.class_level} onChange={(e) => setPF('class_level', e.target.value)} className="input-field" required>
                    {CLASS_LEVELS.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink/90 mb-1">Paper Type *</label>
                  <select value={paperForm.paper_type} onChange={(e) => setPF('paper_type', e.target.value)} className="input-field" required>
                    {PAPER_TYPES.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink/90 mb-1">Year</label>
                  <select value={paperForm.academic_year} onChange={(e) => setPF('academic_year', e.target.value)} className="input-field">
                    {YEARS.map((y) => <option key={y} value={y}>{y}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink/90 mb-1">Language</label>
                  <select value={paperForm.language} onChange={(e) => setPF('language', e.target.value)} className="input-field">
                    {LANGUAGES.map((l) => <option key={l} value={l}>{l}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-ink/90 mb-1">Chapter / Topic</label>
                  <input type="text" value={paperForm.chapter} onChange={(e) => setPF('chapter', e.target.value)} className="input-field" placeholder="optional" />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-ink/90 mb-1">File * (PDF, DOCX, TXT)</label>
                <input
                  type="file"
                  accept={ACCEPT}
                  onChange={(e) => setPF('file', e.target.files[0])}
                  className="w-full text-sm text-muted file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-line file:text-sm file:bg-surface-3/60 hover:file:bg-surface-3"
                  required
                />
                <p className="text-xs text-faint mt-1">Max size: 50MB</p>
              </div>
              {uploading && <ProgressBar />}
              <div className="flex gap-3 pt-1">
                <button type="button" onClick={() => setShowPaperUpload(false)} className="btn-secondary flex-1" disabled={uploading}>Cancel</button>
                <button type="submit" disabled={uploading} className="btn-primary flex-1 flex items-center justify-center gap-2 bg-purple-600 hover:bg-purple-700 focus:ring-purple-500">
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
