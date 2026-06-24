import { useState, useEffect, useRef } from 'react';
import Layout from '../../components/Layout';
import { adminAPI } from '../../services/api';
import {
  Upload, FileSpreadsheet, Download, RotateCcw, Loader2, CheckCircle,
  AlertCircle, X, Users, Info, Clock, XCircle,
} from 'lucide-react';

const DUP_MODES = [
  { value: 'skip', label: 'Skip existing records', hint: 'Existing registration numbers are left unchanged.' },
  { value: 'update', label: 'Update existing records', hint: 'Existing students get their name / father / class updated.' },
  { value: 'create_new', label: 'Create new records only', hint: 'Only brand-new registration numbers are added.' },
];

const PW_MODES = [
  { value: 'registration', label: 'Registration number as password', hint: 'Each student’s password is their registration number.' },
  { value: 'custom', label: 'Custom password (same for all)', hint: 'One password you set is used for every new student.' },
  { value: 'random', label: 'Random password per student', hint: 'A unique random password is generated for each student.' },
];

const SECTION_MODES = [
  { value: 'create', label: 'Auto-create missing sections', hint: 'Any section in the file is accepted and assigned to the student.' },
  { value: 'strict', label: 'Skip if section doesn’t exist', hint: 'Only sections already used by students in that class are allowed; others are reported and skipped.' },
];

const TERMINAL = ['completed', 'failed', 'rolled_back'];

const STATUS_BADGE = {
  pending: 'badge-yellow', processing: 'badge-blue', completed: 'badge-green',
  failed: 'badge-red', rolled_back: 'badge-gray',
};

function downloadBlob(data, filename) {
  const url = window.URL.createObjectURL(new Blob([data]));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  window.URL.revokeObjectURL(url);
}

export default function BulkImportStudents() {
  const [file, setFile] = useState(null);
  const [duplicateMode, setDuplicateMode] = useState('skip');
  const [passwordMode, setPasswordMode] = useState('registration');
  const [sectionMode, setSectionMode] = useState('create');
  const [customPassword, setCustomPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  const [activeBatch, setActiveBatch] = useState(null); // batch currently being watched / shown
  const [batches, setBatches] = useState([]);
  const [rollingBack, setRollingBack] = useState(null);
  const pollRef = useRef(null);

  const flash = (msg) => { setSuccess(msg); setTimeout(() => setSuccess(''), 4000); };

  const loadBatches = async () => {
    try {
      const { data } = await adminAPI.getImportBatches();
      setBatches(data);
    } catch (e) { /* non-fatal */ }
  };

  useEffect(() => { loadBatches(); }, []);

  // Poll the active batch until it reaches a terminal state.
  useEffect(() => {
    if (!activeBatch || TERMINAL.includes(activeBatch.status)) {
      if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      return;
    }
    pollRef.current = setInterval(async () => {
      try {
        const { data } = await adminAPI.getImportBatch(activeBatch.id);
        setActiveBatch(data);
        if (TERMINAL.includes(data.status)) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          loadBatches();
        }
      } catch (e) { /* keep polling */ }
    }, 2500);
    return () => { if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; } };
  }, [activeBatch?.id, activeBatch?.status]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!file) { setError('Please choose an Excel (.xlsx) file'); return; }
    if (passwordMode === 'custom' && customPassword.trim().length < 4) {
      setError('Enter a custom password (at least 4 characters)');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const { data } = await adminAPI.bulkImportStudents({
        file,
        duplicate_mode: duplicateMode,
        password_mode: passwordMode,
        section_mode: sectionMode,
        custom_password: passwordMode === 'custom' ? customPassword.trim() : undefined,
      });
      setActiveBatch(data);
      setFile(null);
      flash('Import started — processing in the background…');
      loadBatches();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to start import');
    } finally {
      setSubmitting(false);
    }
  };

  const downloadCredentials = async (id) => {
    try {
      const { data } = await adminAPI.downloadImportCredentials(id);
      downloadBlob(data, `student_credentials_${id.slice(0, 8)}.xlsx`);
    } catch (e) {
      setError('Credentials file is not available for this import');
    }
  };

  const rollback = async (id) => {
    if (!confirm('Roll back this import? All student accounts created by it will be permanently deleted. Existing and updated records are preserved.')) return;
    setRollingBack(id);
    setError('');
    try {
      const { data } = await adminAPI.rollbackImport(id);
      flash(data.message || 'Import rolled back');
      if (activeBatch?.id === id) {
        const { data: fresh } = await adminAPI.getImportBatch(id);
        setActiveBatch(fresh);
      }
      loadBatches();
    } catch (err) {
      setError(err.response?.data?.detail || 'Rollback failed');
    } finally {
      setRollingBack(null);
    }
  };

  const canRollback = (b) => b.status === 'completed' && !b.is_rolled_back && b.created_count_remaining > 0;

  const SummaryStat = ({ label, value, color }) => (
    <div className="card p-3 text-center">
      <div className={`text-2xl font-bold ${color}`}>{value}</div>
      <div className="text-xs text-muted mt-0.5">{label}</div>
    </div>
  );

  return (
    <Layout title="Bulk Import Students">
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

      {/* Info banner */}
      <div className="p-4 bg-blue-50 rounded-xl border border-blue-200 mb-5 text-sm text-blue-800">
        <p className="font-semibold mb-1 flex items-center gap-1.5"><Info size={15} /> Excel Format</p>
        <p>
          Upload an <strong>.xlsx</strong> file with these columns:
          <span className="font-medium"> Registration Number, Student Name, Father Name, Class, Section</span>.
          A login account is created for each student (username = registration number) and linked to
          their class and section. Large files (800–1000+ students) are processed in the background —
          you can leave this page and check back; the import keeps running.
        </p>
      </div>

      <div className="grid lg:grid-cols-2 gap-5">
        {/* Upload form */}
        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <FileSpreadsheet size={18} className="text-emerald-600" />
            <h2 className="font-bold text-ink">Upload Student File</h2>
          </div>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-ink/90 mb-1">Excel File (.xlsx) *</label>
              <input
                type="file"
                accept=".xlsx,.xlsm"
                onChange={(e) => setFile(e.target.files[0])}
                className="w-full text-sm text-muted file:mr-3 file:py-1.5 file:px-3 file:rounded-lg file:border file:border-line file:text-sm file:bg-surface-3/60 hover:file:bg-surface-3"
              />
              {file && <p className="text-xs text-faint mt-1">{file.name}</p>}
            </div>

            <div>
              <label className="block text-sm font-medium text-ink/90 mb-1">If a registration number already exists</label>
              <select value={duplicateMode} onChange={(e) => setDuplicateMode(e.target.value)} className="input-field">
                {DUP_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
              <p className="text-xs text-faint mt-1">{DUP_MODES.find((m) => m.value === duplicateMode)?.hint}</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-ink/90 mb-1">If a section doesn’t exist for the class</label>
              <select value={sectionMode} onChange={(e) => setSectionMode(e.target.value)} className="input-field">
                {SECTION_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
              <p className="text-xs text-faint mt-1">{SECTION_MODES.find((m) => m.value === sectionMode)?.hint}</p>
            </div>

            <div>
              <label className="block text-sm font-medium text-ink/90 mb-1">Default password</label>
              <select value={passwordMode} onChange={(e) => setPasswordMode(e.target.value)} className="input-field">
                {PW_MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
              </select>
              <p className="text-xs text-faint mt-1">{PW_MODES.find((m) => m.value === passwordMode)?.hint}</p>
            </div>

            {passwordMode === 'custom' && (
              <div>
                <label className="block text-sm font-medium text-ink/90 mb-1">Custom password *</label>
                <input
                  type="text"
                  value={customPassword}
                  onChange={(e) => setCustomPassword(e.target.value)}
                  className="input-field"
                  placeholder="e.g. School@123"
                />
              </div>
            )}

            <p className="text-xs text-faint">Students are required to change their password on first login.</p>

            <button type="submit" disabled={submitting} className="btn-primary w-full flex items-center justify-center gap-2">
              {submitting ? <><Loader2 size={16} className="animate-spin" /> Starting…</> : <><Upload size={16} /> Start Import</>}
            </button>
          </form>
        </div>

        {/* Active batch status */}
        <div className="card">
          <div className="flex items-center gap-2 mb-4">
            <Users size={18} className="text-brand-blue" />
            <h2 className="font-bold text-ink">Import Status</h2>
          </div>

          {!activeBatch ? (
            <div className="text-center py-10 text-sm text-faint">
              <Clock size={32} className="mx-auto mb-2 text-faint" />
              No active import. Upload a file to begin, or pick one from the history below.
            </div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <div className="text-sm text-muted truncate">{activeBatch.filename || 'Import'}</div>
                <span className={STATUS_BADGE[activeBatch.status] || 'badge-gray'}>{activeBatch.status}</span>
              </div>

              {(activeBatch.status === 'pending' || activeBatch.status === 'processing') && (
                <div className="flex items-center gap-2 text-sm text-blue-700">
                  <Loader2 size={16} className="animate-spin" />
                  Processing in the background… {activeBatch.total ? `(${activeBatch.total} rows)` : ''}
                </div>
              )}

              {activeBatch.status === 'failed' && (
                <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-start gap-2">
                  <XCircle size={16} className="mt-0.5 shrink-0" />
                  <span>{activeBatch.error_message || 'Import failed.'}</span>
                </div>
              )}

              {TERMINAL.includes(activeBatch.status) && activeBatch.status !== 'failed' && (
                <>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                    <SummaryStat label="Total" value={activeBatch.total} color="text-ink" />
                    <SummaryStat label="Imported" value={activeBatch.created_count} color="text-green-600" />
                    <SummaryStat label="Updated" value={activeBatch.updated_count} color="text-blue-600" />
                    <SummaryStat label="Skipped" value={activeBatch.skipped_count} color="text-amber-600" />
                    <SummaryStat label="Failed" value={activeBatch.failed_count} color="text-red-600" />
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {activeBatch.has_credentials && (
                      <button onClick={() => downloadCredentials(activeBatch.id)} className="btn-primary flex items-center gap-2">
                        <Download size={15} /> Download Credentials
                      </button>
                    )}
                    {canRollback(activeBatch) && (
                      <button
                        onClick={() => rollback(activeBatch.id)}
                        disabled={rollingBack === activeBatch.id}
                        className="btn-secondary flex items-center gap-2 text-red-600"
                      >
                        {rollingBack === activeBatch.id ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />}
                        Roll Back
                      </button>
                    )}
                  </div>

                  {activeBatch.is_rolled_back && (
                    <p className="text-xs text-faint">This import was rolled back — its created accounts were removed.</p>
                  )}

                  {/* Error log */}
                  {activeBatch.error_log?.length > 0 && (
                    <div>
                      <h3 className="font-semibold text-sm text-ink/90 mb-2">Error / Skip Log ({activeBatch.error_log.length})</h3>
                      <div className="max-h-60 overflow-y-auto border border-line rounded-lg">
                        <table className="w-full text-xs">
                          <thead className="bg-surface-3/60 sticky top-0">
                            <tr>
                              <th className="text-left p-2 font-semibold">Row</th>
                              <th className="text-left p-2 font-semibold">Reg #</th>
                              <th className="text-left p-2 font-semibold">Name</th>
                              <th className="text-left p-2 font-semibold">Reason</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-line">
                            {activeBatch.error_log.map((e, i) => (
                              <tr key={i}>
                                <td className="p-2 text-faint">{e.row || '—'}</td>
                                <td className="p-2 font-mono">{e.reg_no || '—'}</td>
                                <td className="p-2">{e.name || '—'}</td>
                                <td className="p-2 text-amber-700">{e.reason}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Import history */}
      <div className="card mt-5 p-0 overflow-hidden">
        <div className="p-4 border-b border-line flex items-center gap-2">
          <Clock size={16} className="text-muted" />
          <h2 className="font-bold text-ink">Recent Imports</h2>
        </div>
        {batches.length === 0 ? (
          <div className="text-center py-10 text-sm text-faint">No imports yet.</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-surface-3/60 border-b border-line">
                <tr>
                  <th className="text-left p-3 font-semibold text-muted">File</th>
                  <th className="text-left p-3 font-semibold text-muted">Status</th>
                  <th className="text-left p-3 font-semibold text-muted hidden sm:table-cell">Imported / Updated / Skipped / Failed</th>
                  <th className="text-right p-3 font-semibold text-muted">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {batches.map((b) => (
                  <tr
                    key={b.id}
                    className={`hover:bg-surface-3/60 transition-colors cursor-pointer ${activeBatch?.id === b.id ? 'bg-surface-3/40' : ''}`}
                    onClick={() => adminAPI.getImportBatch(b.id).then(({ data }) => setActiveBatch(data))}
                  >
                    <td className="p-3">
                      <div className="font-medium text-ink truncate max-w-[180px]">{b.filename || 'Import'}</div>
                      <div className="text-xs text-faint">{b.created_at ? new Date(b.created_at).toLocaleString() : ''}</div>
                    </td>
                    <td className="p-3"><span className={STATUS_BADGE[b.status] || 'badge-gray'}>{b.status}</span></td>
                    <td className="p-3 hidden sm:table-cell text-xs text-muted">
                      <span className="text-green-600 font-medium">{b.created_count}</span> / {b.updated_count} / {b.skipped_count} / <span className="text-red-600">{b.failed_count}</span>
                    </td>
                    <td className="p-3" onClick={(e) => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1.5">
                        {b.has_credentials && (
                          <button onClick={() => downloadCredentials(b.id)} className="p-1.5 rounded hover:bg-surface-3 text-faint hover:text-blue-600" title="Download credentials">
                            <Download size={15} />
                          </button>
                        )}
                        {canRollback(b) && (
                          <button
                            onClick={() => rollback(b.id)}
                            disabled={rollingBack === b.id}
                            className="p-1.5 rounded hover:bg-surface-3 text-faint hover:text-red-600"
                            title="Roll back this import"
                          >
                            {rollingBack === b.id ? <Loader2 size={15} className="animate-spin" /> : <RotateCcw size={15} />}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </Layout>
  );
}
