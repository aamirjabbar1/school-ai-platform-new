import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import {
  Pencil, Highlighter, Eraser, Type, Square, Circle, Minus,
  Undo2, Redo2, Trash2, Plus, ChevronLeft, ChevronRight, Save,
} from 'lucide-react';

// ─── Interactive whiteboard ───────────────────────────────────────────────────
//
// Built on plain pointer events rather than a drawing library, for two reasons
// that matter in a classroom: a teacher writing with a stylus on a tablet and a
// teacher with a mouse must behave identically, and the stroke format has to be
// something we can send over the wire, save with the lesson and re-render later.
//
// A stroke is {tool, color, width, points:[x,y,…]} in normalised 0–1
// coordinates, so a board drawn on a 13" laptop lands correctly on a 6" phone.
// Coordinates are the only thing that travels; each device renders its own.

const TOOLS = [
  { id: 'pen', icon: Pencil, label: 'Pen' },
  { id: 'highlighter', icon: Highlighter, label: 'Highlight' },
  { id: 'line', icon: Minus, label: 'Line' },
  { id: 'rect', icon: Square, label: 'Box' },
  { id: 'ellipse', icon: Circle, label: 'Circle' },
  { id: 'text', icon: Type, label: 'Text' },
  { id: 'eraser', icon: Eraser, label: 'Erase' },
];

const COLORS = ['#0f172a', '#2563eb', '#dc2626', '#16a34a', '#f59e0b', '#ffffff'];
const WIDTHS = [2, 4, 8, 14];

const Whiteboard = forwardRef(function Whiteboard({
  editable = false,
  transparent = false,
  strokes = [],
  liveStrokes = [],
  onStroke,
  onStrokeProgress,
  onClear,
  onUndo,
  pageCount = 1,
  pageIndex = 0,
  onPageChange,
  onAddPage,
  onSave,
  saving = false,
}, ref) {
  const canvasRef = useRef(null);
  const drawingRef = useRef(null);
  const [tool, setTool] = useState('pen');
  const [color, setColor] = useState(transparent ? '#dc2626' : '#0f172a');
  const [width, setWidth] = useState(4);

  // ── Rendering ─────────────────────────────────────────────────────────────
  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    if (!transparent) {
      ctx.fillStyle = '#f8fafc';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
    }

    // Remote strokes still being drawn are painted too, so students watch the
    // teacher write rather than waiting for them to lift the pen.
    [...strokes, ...liveStrokes, drawingRef.current].filter(Boolean).forEach((stroke) => {
      drawStroke(ctx, stroke, canvas.width, canvas.height);
    });
  }, [strokes, liveStrokes, transparent]);

  // Canvas pixels must track the element's real size or strokes land in the
  // wrong place after a rotation or a sidebar opening.
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      redraw();
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, [redraw]);

  useEffect(redraw, [redraw]);

  useImperativeHandle(ref, () => ({
    toPNG: () => canvasRef.current?.toDataURL('image/png'),
  }), []);

  // ── Input ─────────────────────────────────────────────────────────────────
  const pointFrom = (event) => {
    const rect = canvasRef.current.getBoundingClientRect();
    return [
      Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width)),
      Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height)),
    ];
  };

  const handleDown = (event) => {
    if (!editable) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);

    if (tool === 'text') {
      // eslint-disable-next-line no-alert
      const value = window.prompt('Text to write on the board:');
      if (!value) return;
      const [x, y] = pointFrom(event);
      commit({ tool: 'text', color, width, points: [x, y], text: value });
      return;
    }

    drawingRef.current = {
      tool,
      color: tool === 'eraser' ? (transparent ? 'erase' : '#f8fafc') : color,
      width: tool === 'highlighter' ? width * 3 : tool === 'eraser' ? width * 4 : width,
      points: pointFrom(event),
    };
    redraw();
  };

  const handleMove = (event) => {
    const stroke = drawingRef.current;
    if (!editable || !stroke) return;

    const [x, y] = pointFrom(event);
    if (stroke.tool === 'pen' || stroke.tool === 'highlighter' || stroke.tool === 'eraser') {
      stroke.points.push(x, y);
    } else {
      // Shapes keep only their start and current corner.
      stroke.points = [stroke.points[0], stroke.points[1], x, y];
    }
    redraw();
    onStrokeProgress?.({ ...stroke, points: [...stroke.points] });
  };

  const handleUp = () => {
    const stroke = drawingRef.current;
    drawingRef.current = null;
    if (!stroke || stroke.points.length < 4) { redraw(); return; }
    commit(stroke);
  };

  const commit = (stroke) => {
    drawingRef.current = null;
    onStroke?.(stroke);
  };

  return (
    <div className="relative w-full h-full flex flex-col">
      <canvas
        ref={canvasRef}
        onPointerDown={handleDown}
        onPointerMove={handleMove}
        onPointerUp={handleUp}
        onPointerCancel={handleUp}
        onPointerLeave={handleUp}
        className={`flex-1 w-full rounded-2xl ${transparent ? '' : 'bg-slate-50'}
                    ${editable ? 'cursor-crosshair touch-none' : 'pointer-events-none'}`}
      />

      {editable && (
        <div className="mt-2 flex items-center gap-1.5 flex-wrap glass-strong rounded-2xl p-2">
          {TOOLS.map(({ id, icon: Icon, label }) => (
            <button
              key={id}
              onClick={() => setTool(id)}
              title={label}
              className={`p-2.5 rounded-xl transition-colors ${
                tool === id ? 'bg-brand-blue text-white' : 'text-ink hover:bg-surface-3'}`}
            >
              <Icon size={18} />
            </button>
          ))}

          <span className="w-px h-6 bg-line mx-1" />

          {COLORS.map((c) => (
            <button
              key={c}
              onClick={() => setColor(c)}
              title="Colour"
              style={{ background: c }}
              className={`w-7 h-7 rounded-full border-2 ${
                color === c ? 'border-brand-cyan scale-110' : 'border-line'} transition-transform`}
            />
          ))}

          <span className="w-px h-6 bg-line mx-1" />

          {WIDTHS.map((w) => (
            <button
              key={w}
              onClick={() => setWidth(w)}
              title={`${w}px`}
              className={`w-8 h-8 rounded-xl flex items-center justify-center ${
                width === w ? 'bg-surface-3' : ''}`}
            >
              <span className="rounded-full bg-ink block" style={{ width: w + 2, height: w + 2 }} />
            </button>
          ))}

          <span className="w-px h-6 bg-line mx-1" />

          <button onClick={onUndo} title="Undo" className="p-2.5 rounded-xl hover:bg-surface-3">
            <Undo2 size={18} />
          </button>
          <button onClick={onClear} title="Clear board" className="p-2.5 rounded-xl hover:bg-surface-3 text-rose-400">
            <Trash2 size={18} />
          </button>

          {onPageChange && (
            <>
              <span className="w-px h-6 bg-line mx-1" />
              <button
                onClick={() => onPageChange(Math.max(0, pageIndex - 1))}
                disabled={pageIndex === 0}
                className="p-2.5 rounded-xl hover:bg-surface-3 disabled:opacity-40"
              >
                <ChevronLeft size={18} />
              </button>
              <span className="text-xs font-semibold text-muted px-1">
                {pageIndex + 1} / {pageCount}
              </span>
              <button
                onClick={() => onPageChange(Math.min(pageCount - 1, pageIndex + 1))}
                disabled={pageIndex >= pageCount - 1}
                className="p-2.5 rounded-xl hover:bg-surface-3 disabled:opacity-40"
              >
                <ChevronRight size={18} />
              </button>
              <button onClick={onAddPage} title="New page" className="p-2.5 rounded-xl hover:bg-surface-3">
                <Plus size={18} />
              </button>
            </>
          )}

          {onSave && (
            <button
              onClick={onSave}
              disabled={saving}
              className="btn-primary text-xs ml-auto px-3 py-2"
            >
              <Save size={15} /> {saving ? 'Saving…' : 'Save board'}
            </button>
          )}
        </div>
      )}
    </div>
  );
});

// ─── Stroke rendering ─────────────────────────────────────────────────────────

function drawStroke(ctx, stroke, w, h) {
  const pts = stroke.points || [];
  if (pts.length < 2) return;

  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  ctx.lineWidth = (stroke.width || 4) * (w / 1000);

  if (stroke.color === 'erase') {
    // On an annotation layer there is no paper to paint over, so erasing has to
    // actually remove pixels rather than cover them with white.
    ctx.globalCompositeOperation = 'destination-out';
    ctx.strokeStyle = 'rgba(0,0,0,1)';
  } else {
    ctx.strokeStyle = stroke.color || '#0f172a';
    ctx.fillStyle = stroke.color || '#0f172a';
    if (stroke.tool === 'highlighter') ctx.globalAlpha = 0.35;
  }

  const x = (i) => pts[i] * w;
  const y = (i) => pts[i] * h;

  switch (stroke.tool) {
    case 'text': {
      ctx.globalAlpha = 1;
      ctx.font = `${Math.max(14, (stroke.width || 4) * 4 * (w / 1000) * 1.6)}px Inter, system-ui, sans-serif`;
      ctx.fillText(stroke.text || '', x(0), y(1));
      break;
    }
    case 'line': {
      ctx.beginPath();
      ctx.moveTo(x(0), y(1));
      ctx.lineTo(x(2), y(3));
      ctx.stroke();
      break;
    }
    case 'rect': {
      ctx.beginPath();
      ctx.rect(x(0), y(1), x(2) - x(0), y(3) - y(1));
      ctx.stroke();
      break;
    }
    case 'ellipse': {
      const cx = (x(0) + x(2)) / 2;
      const cy = (y(1) + y(3)) / 2;
      ctx.beginPath();
      ctx.ellipse(cx, cy, Math.abs(x(2) - x(0)) / 2, Math.abs(y(3) - y(1)) / 2, 0, 0, Math.PI * 2);
      ctx.stroke();
      break;
    }
    default: {
      ctx.beginPath();
      ctx.moveTo(x(0), y(1));
      for (let i = 2; i < pts.length; i += 2) ctx.lineTo(x(i), y(i + 1));
      ctx.stroke();
    }
  }

  ctx.restore();
}

export default Whiteboard;
