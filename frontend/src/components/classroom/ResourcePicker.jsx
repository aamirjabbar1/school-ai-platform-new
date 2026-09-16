import { useEffect, useMemo, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { onlineClassAPI } from '../../services/api';
import { BookOpen, Search, X, Loader2, FileText, Image as ImageIcon, Presentation } from 'lucide-react';

// OPEN BOOK — pick from what the Knowledge Base already holds for this class.
// The teacher uploaded these books once, as part of setting up LSS Bot; being
// asked to upload them again for every lesson would be the fastest way to make
// this feature unused.
export default function ResourcePicker({ sessionId, subject, open, onClose, onPresent }) {
  const [resources, setResources] = useState([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [allSubjects, setAllSubjects] = useState(false);
  const [opening, setOpening] = useState('');
  const [preparing, setPreparing] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!open) return;
    setLoading(true);
    onlineClassAPI.resources(sessionId, { all_subjects: allSubjects })
      .then(({ data }) => setResources(data.resources || []))
      .catch(() => setError('Could not load your books.'))
      .finally(() => setLoading(false));
  }, [open, sessionId, allSubjects]);

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return resources;
    return resources.filter((r) => (
      r.title?.toLowerCase().includes(term) || r.chapter?.toLowerCase().includes(term)
    ));
  }, [resources, search]);

  const present = async (resource) => {
    setOpening(resource.document_id);
    setError('');
    try {
      const result = await onPresent(resource.document_id);
      if (result?.state === 'converting') {
        // PowerPoint and Word are converted once, then cached. Keep the teacher
        // informed rather than leaving them looking at nothing in front of a class.
        setPreparing(resource.document_id);
        pollConversion(resource.document_id);
        return;
      }
      onClose();
    } catch (err) {
      setError(err?.response?.data?.detail || 'This document could not be opened.');
    } finally {
      setOpening('');
    }
  };

  const pollConversion = (documentId) => {
    const timer = setInterval(async () => {
      try {
        const { data } = await onlineClassAPI.conversionStatus(sessionId, documentId);
        if (data.state === 'ready') {
          clearInterval(timer);
          setPreparing('');
          await onPresent(documentId);
          onClose();
        } else if (data.state === 'failed' || data.state === 'unsupported') {
          clearInterval(timer);
          setPreparing('');
          setError('This document could not be prepared. Try Share Screen instead.');
        }
      } catch {
        clearInterval(timer);
        setPreparing('');
      }
    }, 3000);
  };

  const iconFor = (resource) => {
    if (resource.kind === 'image') return ImageIcon;
    if (['pptx', 'ppt', 'odp'].includes(resource.file_type)) return Presentation;
    return FileText;
  };

  return (
    <AnimatePresence>
      {open && (
        <div className="fixed inset-0 z-50">
          <motion.div
            initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="absolute inset-0 bg-slate-950/60 backdrop-blur-sm" onClick={onClose}
          />
          <motion.div
            initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 24 }}
            className="absolute inset-x-0 bottom-0 sm:inset-0 sm:m-auto sm:max-w-2xl sm:h-[80vh]
                       glass-strong rounded-t-3xl sm:rounded-3xl p-5 flex flex-col max-h-[85vh]"
          >
            <div className="flex items-center gap-3 mb-4">
              <BookOpen size={20} className="text-brand-cyan" />
              <h2 className="font-display font-bold text-lg flex-1">Open a book</h2>
              <button onClick={onClose} className="p-2 rounded-xl hover:bg-surface-3">
                <X size={18} />
              </button>
            </div>

            <div className="flex items-center gap-2 mb-3">
              <div className="relative flex-1">
                <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder="Search your books…"
                  className="input-field pl-9"
                />
              </div>
              <label className="flex items-center gap-1.5 text-xs text-muted whitespace-nowrap">
                <input
                  type="checkbox"
                  checked={allSubjects}
                  onChange={(e) => setAllSubjects(e.target.checked)}
                />
                All subjects
              </label>
            </div>

            {error && <div className="text-sm text-rose-400 mb-2">{error}</div>}

            <div className="flex-1 overflow-y-auto space-y-2">
              {loading && (
                <div className="flex items-center gap-2 text-muted text-sm py-6 justify-center">
                  <Loader2 className="animate-spin" size={18} /> Loading your books…
                </div>
              )}

              {!loading && filtered.length === 0 && (
                <p className="text-sm text-muted text-center py-6">
                  Nothing here yet for {subject}. Ask an administrator to add it to the
                  Knowledge Base, or use Share Screen.
                </p>
              )}

              {filtered.map((resource) => {
                const Icon = iconFor(resource);
                const busy = opening === resource.document_id || preparing === resource.document_id;
                return (
                  <button
                    key={resource.document_id}
                    onClick={() => present(resource)}
                    disabled={busy}
                    className="w-full glass rounded-2xl p-3 flex items-center gap-3 text-left
                               hover:shadow-glow transition-shadow disabled:opacity-70"
                  >
                    <div className="w-10 h-10 rounded-xl bg-surface-3 flex items-center justify-center text-brand-cyan shrink-0">
                      {busy ? <Loader2 size={18} className="animate-spin" /> : <Icon size={18} />}
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="font-medium text-sm truncate">{resource.title}</div>
                      <div className="text-xs text-muted truncate">
                        {resource.class_level} · {resource.subject}
                        {resource.chapter ? ` · ${resource.chapter}` : ''}
                        {resource.page_count ? ` · ${resource.page_count} pages` : ''}
                      </div>
                    </div>
                    {preparing === resource.document_id && (
                      <span className="text-xs text-muted">Preparing…</span>
                    )}
                  </button>
                );
              })}
            </div>
          </motion.div>
        </div>
      )}
    </AnimatePresence>
  );
}
