import { useEffect, useRef, useState } from 'react';
import * as pdfjsLib from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import { ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Loader2, FileWarning } from 'lucide-react';
import Whiteboard from './Whiteboard';

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

// ─── Book / document presentation (spec §7) ───────────────────────────────────
//
// Each device renders the page itself from the Knowledge Base file; only the
// page number and the teacher's annotations cross the network. A shared page
// therefore costs a few hundred bytes instead of a video stream, and stays
// crisp on a phone — which is what makes this usable on a home connection.
//
// The teacher draws on a transparent layer above the page, so circling a
// diagram never damages the book.

export default function BookViewer({
  fileUrl,
  kind = 'pdf',
  page = 1,
  zoom = 1,
  editable = false,
  annotations = [],
  onStroke,
  onClearAnnotations,
  onUndoAnnotation,
  onPageChange,
  onZoomChange,
  onLoaded,
}) {
  const canvasRef = useRef(null);
  const docRef = useRef(null);
  const renderTaskRef = useRef(null);
  const [pageCount, setPageCount] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // ── Load the document ─────────────────────────────────────────────────────
  useEffect(() => {
    if (kind !== 'pdf' || !fileUrl) return undefined;
    let cancelled = false;
    setLoading(true);
    setError('');

    const task = pdfjsLib.getDocument({ url: fileUrl, withCredentials: false });
    task.promise
      .then((doc) => {
        if (cancelled) { doc.destroy(); return; }
        docRef.current = doc;
        setPageCount(doc.numPages);
        onLoaded?.(doc.numPages);
        setLoading(false);
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err?.message || 'This document could not be opened.');
        setLoading(false);
      });

    return () => {
      cancelled = true;
      task.destroy?.();
      docRef.current?.destroy?.();
      docRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileUrl, kind]);

  // ── Render the current page ───────────────────────────────────────────────
  useEffect(() => {
    if (kind !== 'pdf') return;
    const doc = docRef.current;
    const canvas = canvasRef.current;
    if (!doc || !canvas) return;

    let cancelled = false;
    const target = Math.min(Math.max(1, page), doc.numPages);

    doc.getPage(target).then((pdfPage) => {
      if (cancelled) return;
      // Cancel any in-flight render: flicking through pages quickly otherwise
      // paints an older page over a newer one.
      renderTaskRef.current?.cancel?.();

      const container = canvas.parentElement;
      const base = pdfPage.getViewport({ scale: 1 });
      const fit = (container?.clientWidth || base.width) / base.width;
      const viewport = pdfPage.getViewport({ scale: Math.max(0.2, fit * (zoom || 1)) });

      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      canvas.style.width = '100%';
      canvas.style.height = 'auto';

      const task = pdfPage.render({ canvasContext: canvas.getContext('2d'), viewport });
      renderTaskRef.current = task;
      task.promise.catch(() => { /* superseded by a newer page */ });
    });

    return () => { cancelled = true; };
  }, [page, zoom, kind, pageCount]);

  if (kind === 'image') {
    return (
      <div className="relative w-full h-full flex items-center justify-center overflow-auto rounded-2xl bg-slate-50">
        <img src={fileUrl} alt="Lesson resource" className="max-w-full max-h-full object-contain" />
        <div className="absolute inset-0">
          <Whiteboard
            transparent
            editable={editable}
            strokes={annotations}
            onStroke={onStroke}
            onClear={onClearAnnotations}
            onUndo={onUndoAnnotation}
          />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="w-full h-full flex flex-col items-center justify-center gap-3 text-muted">
        <FileWarning size={34} />
        <p className="text-sm text-center max-w-xs">{error}</p>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full flex flex-col">
      <div className="relative flex-1 overflow-auto rounded-2xl bg-slate-100">
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-muted gap-2">
            <Loader2 className="animate-spin" size={20} /> Opening the book…
          </div>
        )}
        <div className="relative w-full">
          <canvas ref={canvasRef} className="w-full block" />
          {/* Annotation layer: sits exactly over the page */}
          <div className="absolute inset-0">
            <Whiteboard
              transparent
              editable={editable}
              strokes={annotations}
              onStroke={onStroke}
              onClear={onClearAnnotations}
              onUndo={onUndoAnnotation}
            />
          </div>
        </div>
      </div>

      {editable && (
        <div className="mt-2 flex items-center justify-center gap-2 glass-strong rounded-2xl p-2">
          <button
            onClick={() => onPageChange?.(Math.max(1, page - 1))}
            disabled={page <= 1}
            className="p-2.5 rounded-xl hover:bg-surface-3 disabled:opacity-40"
          >
            <ChevronLeft size={18} />
          </button>
          <span className="text-sm font-semibold px-2">Page {page} / {pageCount}</span>
          <button
            onClick={() => onPageChange?.(Math.min(pageCount, page + 1))}
            disabled={page >= pageCount}
            className="p-2.5 rounded-xl hover:bg-surface-3 disabled:opacity-40"
          >
            <ChevronRight size={18} />
          </button>
          <span className="w-px h-6 bg-line mx-1" />
          <button onClick={() => onZoomChange?.(Math.max(0.5, (zoom || 1) - 0.25))} className="p-2.5 rounded-xl hover:bg-surface-3">
            <ZoomOut size={18} />
          </button>
          <span className="text-xs text-muted w-12 text-center">{Math.round((zoom || 1) * 100)}%</span>
          <button onClick={() => onZoomChange?.(Math.min(3, (zoom || 1) + 0.25))} className="p-2.5 rounded-xl hover:bg-surface-3">
            <ZoomIn size={18} />
          </button>
        </div>
      )}
    </div>
  );
}
