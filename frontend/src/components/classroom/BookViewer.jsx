import { useCallback, useEffect, useRef, useState } from 'react';
import * as pdfjsLib from 'pdfjs-dist';
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';
import {
  ChevronLeft, ChevronRight, ZoomIn, ZoomOut, Loader2, FileWarning, Hand, Pencil,
} from 'lucide-react';
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
  const scrollRef = useRef(null);
  const docRef = useRef(null);
  const renderTaskRef = useRef(null);
  const [pageCount, setPageCount] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  // A finger cannot do two things at once. While the teacher is drawing, the
  // page cannot be swiped; while it can be swiped, the teacher is not drawing.
  // Touch devices start on swiping, because a teacher who cannot move the page
  // is stuck with a fifth of it and a scrollbar too thin to catch. A mouse
  // scrolls with its wheel whatever this says, so it starts on drawing.
  const [panning, setPanning] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia?.('(pointer: coarse)').matches,
  );
  const drawing = editable && !panning;

  // ── Load the document ─────────────────────────────────────────────────────
  useEffect(() => {
    if (kind !== 'pdf' || !fileUrl) return undefined;
    let cancelled = false;
    setLoading(true);
    setError('');

    // Fetch the pages being taught, not the whole textbook.
    //
    // Left to itself pdf.js pulls the entire file down in the background, and
    // a scanned textbook is hundreds of megabytes: a class waited about ten
    // minutes for page one, and waited again on every rejoin. With streaming
    // and the background fetch off it reads the index, then the few hundred
    // kilobytes that make up the page on screen, over range requests.
    const task = pdfjsLib.getDocument({
      url: fileUrl,
      withCredentials: false,
      disableAutoFetch: true,
      disableStream: true,
      rangeChunkSize: 262144,
    });
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
        // pdf.js messages ("Setting up fake worker failed…") mean nothing to a
        // teacher in front of a class. Keep the detail for whoever debugs it.
        console.warn('[BookViewer] could not open document:', err);
        setError('This book could not be opened. Check the connection and try again.');
        setLoading(false);
      });

    return () => {
      cancelled = true;
      task.destroy?.();
      docRef.current?.destroy?.();
      docRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileUrl, kind, attempt]);

  // ── Render the current page ───────────────────────────────────────────────
  //
  // The page is drawn to the width of the screen it is on, so a phone shows a
  // full-width page rather than the top-left corner of a desktop-sized one,
  // and is drawn at the screen's own pixel density so the small print in a
  // textbook survives. Density is capped at 2: past that a page costs memory a
  // cheap phone does not have, for detail no eye gains.
  const renderPage = useCallback(() => {
    if (kind !== 'pdf') return;
    const doc = docRef.current;
    const canvas = canvasRef.current;
    const box = scrollRef.current;
    if (!doc || !canvas) return;

    const target = Math.min(Math.max(1, page), doc.numPages);
    doc.getPage(target).then((pdfPage) => {
      if (canvasRef.current !== canvas) return;
      // Cancel any in-flight render: flicking through pages quickly otherwise
      // paints an older page over a newer one.
      renderTaskRef.current?.cancel?.();

      const base = pdfPage.getViewport({ scale: 1 });
      const width = box?.clientWidth || canvas.parentElement?.clientWidth || base.width;
      const fit = Math.max(0.2, (width / base.width) * (zoom || 1));
      const density = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = pdfPage.getViewport({ scale: fit * density });

      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      canvas.style.width = '100%';
      canvas.style.height = 'auto';

      const task = pdfPage.render({ canvasContext: canvas.getContext('2d'), viewport });
      renderTaskRef.current = task;
      task.promise.catch(() => { /* superseded by a newer page */ });
    }).catch(() => { /* the document went away underneath us */ });
  }, [page, zoom, kind]);

  useEffect(() => { renderPage(); }, [renderPage, pageCount]);

  // Fetch the page after this one while the class is looking at this one.
  // Only what the book needs to draw it, and only once the current page is on
  // screen, so a teacher turning a page in front of thirty children waits for
  // nothing. Failures are beneath notice: this is a guess about what comes
  // next, and the page turn itself would fetch it anyway.
  useEffect(() => {
    const doc = docRef.current;
    if (kind !== 'pdf' || !doc || loading) return undefined;
    const next = page + 1;
    if (next > doc.numPages) return undefined;
    const ahead = setTimeout(() => {
      doc.getPage(next).then((p) => p.getOperatorList?.()).catch(() => {});
    }, 400);
    return () => clearTimeout(ahead);
  }, [page, kind, loading, pageCount]);

  // Turning a phone on its side changes the width the page should be drawn to.
  useEffect(() => {
    const box = scrollRef.current;
    if (!box || typeof ResizeObserver === 'undefined') return undefined;
    let drawnAt = box.clientWidth;
    const observer = new ResizeObserver(() => {
      // Only a real change in width is worth redrawing a whole page for.
      if (Math.abs(box.clientWidth - drawnAt) < 8) return;
      drawnAt = box.clientWidth;
      renderPage();
    });
    observer.observe(box);
    return () => observer.disconnect();
  }, [renderPage]);

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
        <button onClick={() => setAttempt((n) => n + 1)} className="btn-secondary text-sm">
          Try again
        </button>
      </div>
    );
  }

  return (
    <div className="relative w-full h-full flex flex-col">
      <div
        ref={scrollRef}
        className="relative flex-1 overflow-auto rounded-2xl bg-slate-100"
        style={{ WebkitOverflowScrolling: 'touch' }}
      >
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center text-muted gap-2">
            <Loader2 className="animate-spin" size={20} /> Opening the book…
          </div>
        )}
        <div className="relative w-full">
          <canvas ref={canvasRef} className="w-full block" />
          {/* Annotation layer: sits exactly over the page. It lets touches
              through to the page underneath unless the teacher is drawing,
              which is what makes the book swipe like any other page. */}
          <div className="absolute inset-0">
            <Whiteboard
              transparent
              editable={drawing}
              strokes={annotations}
              onStroke={onStroke}
              onClear={onClearAnnotations}
              onUndo={onUndoAnnotation}
            />
          </div>
        </div>
      </div>

      {editable && (
        <div className="mt-2 flex items-center justify-center gap-2 glass-strong rounded-2xl p-2 flex-wrap">
          <button
            onClick={() => setPanning((on) => !on)}
            title={panning ? 'Swiping moves the page — tap to draw instead' : 'Drawing — tap to move the page instead'}
            className={`flex items-center gap-1.5 px-3 py-2.5 rounded-xl text-sm font-semibold ${
              panning ? 'bg-brand-blue text-white' : 'text-ink hover:bg-surface-3'}`}
          >
            {panning ? <Hand size={18} /> : <Pencil size={18} />}
            {panning ? 'Move' : 'Draw'}
          </button>

          <span className="w-px h-6 bg-line mx-1" />

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
