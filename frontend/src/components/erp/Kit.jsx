/**
 * The ERP's shared parts.
 *
 * The specification asks for a backend that may be as sophisticated as it needs
 * to be and a front end an untrained person can operate. That is not a styling
 * problem, it is a set of rules, and putting the rules in one file is the only
 * way they survive contact with twenty screens:
 *
 *   • One primary action per screen. Everything else is quieter.
 *   • Nothing destructive or bulk happens without a confirmation that states
 *     the real numbers — "755 students", never "the selected records".
 *   • Plain English labels. "GR Number", never "gr_no"; "Date of birth", never
 *     "DOB"; and never a database word in front of a human.
 *   • Every touch target is at least 44px, because attendance and marks entry
 *     happen on a phone in a corridor.
 *   • An empty screen explains what to do next instead of showing an empty box.
 */
import { motion, AnimatePresence } from 'framer-motion';
import { AlertCircle, CheckCircle2, Loader2, X } from 'lucide-react';

/* ── Feedback ─────────────────────────────────────────────────────────────── */

export function Busy({ label = 'Loading…' }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 gap-3">
      <Loader2 className="w-8 h-8 animate-spin text-brand-cyan" />
      <p className="text-muted text-sm">{label}</p>
    </div>
  );
}

export function Note({ kind = 'info', children }) {
  if (!children) return null;
  const tone = {
    info: 'border-brand-cyan/40 text-ink',
    good: 'border-emerald-500/50 text-ink',
    bad: 'border-rose-500/50 text-ink',
  }[kind];
  const Icon = kind === 'bad' ? AlertCircle : CheckCircle2;
  return (
    <div className={`glass rounded-2xl px-4 py-3 border ${tone} flex items-start gap-3 text-sm`}>
      <Icon size={18} className={kind === 'bad' ? 'text-rose-400 mt-0.5' : 'text-emerald-400 mt-0.5'} />
      <div className="flex-1">{children}</div>
    </div>
  );
}

/* ── Numbers ──────────────────────────────────────────────────────────────── */

export function Stat({ icon: Icon, value, label, tone = 'default' }) {
  const ring = {
    default: 'from-brand-blue via-brand-cyan to-brand-teal',
    warn: 'from-amber-500 via-orange-400 to-rose-400',
  }[tone];
  return (
    <div className="card flex items-center gap-4">
      <div className={`w-12 h-12 rounded-2xl bg-gradient-to-br ${ring} flex items-center justify-center text-white shrink-0`}>
        {Icon ? <Icon size={22} /> : null}
      </div>
      <div className="min-w-0">
        <div className="text-2xl font-bold text-ink leading-tight">{value}</div>
        <div className="text-sm text-muted truncate">{label}</div>
      </div>
    </div>
  );
}

/**
 * One thing that needs a human, with the single button that resolves it.
 *
 * Exception-based management (spec §73) only works if the exception carries its
 * own remedy — a list of problems with no button is just a list of problems.
 */
export function Attention({ count, label, actionLabel, onAction, busy }) {
  return (
    <div className="card flex flex-col sm:flex-row sm:items-center gap-4">
      <div className="flex items-center gap-3 flex-1 min-w-0">
        <div className="w-10 h-10 rounded-xl bg-amber-500/15 text-amber-400 flex items-center justify-center shrink-0">
          <AlertCircle size={20} />
        </div>
        <div className="min-w-0">
          <span className="text-lg font-bold text-ink">{count}</span>{' '}
          <span className="text-muted">{label}</span>
        </div>
      </div>
      {actionLabel && (
        <button onClick={onAction} disabled={busy} className="btn-primary min-h-[44px] shrink-0">
          {busy ? <Loader2 size={16} className="animate-spin" /> : null}
          {actionLabel}
        </button>
      )}
    </div>
  );
}

/* ── Confirmation ─────────────────────────────────────────────────────────── */

/**
 * The confirm step of "click → select → confirm → done".
 *
 * `lines` are shown as the plain-English consequences of pressing the button.
 * A confirmation that does not say what will actually happen is a rubber stamp,
 * and people learn to click through it.
 */
export function Confirm({ open, title, lines = [], confirmLabel = 'Yes, do it', onConfirm, onCancel, busy, danger }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex items-end sm:items-center justify-center p-4 bg-black/50 backdrop-blur-sm"
          onClick={busy ? undefined : onCancel}
        >
          <motion.div
            initial={{ y: 30, opacity: 0 }} animate={{ y: 0, opacity: 1 }} exit={{ y: 20, opacity: 0 }}
            onClick={(e) => e.stopPropagation()}
            className="glass-strong rounded-3xl w-full max-w-md p-6"
          >
            <h3 className="text-xl font-bold text-ink mb-3">{title}</h3>
            <ul className="space-y-2 mb-6">
              {lines.map((line, i) => (
                <li key={i} className="flex gap-2 text-sm text-muted">
                  <span className="text-brand-cyan">•</span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
            <div className="flex flex-col-reverse sm:flex-row gap-3 sm:justify-end">
              <button onClick={onCancel} disabled={busy} className="btn-secondary min-h-[44px]">
                Cancel
              </button>
              <button
                onClick={onConfirm}
                disabled={busy}
                className={`${danger ? 'btn-danger' : 'btn-primary'} min-h-[44px]`}
              >
                {busy ? <Loader2 size={16} className="animate-spin" /> : null}
                {busy ? 'Working…' : confirmLabel}
              </button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/* ── Input ────────────────────────────────────────────────────────────────── */

export function Field({ label, value, onChange, type = 'text', hint, options, placeholder, required }) {
  const base =
    'w-full min-h-[44px] rounded-xl px-3 py-2 bg-surface-2 border border-line text-ink ' +
    'focus:outline-none focus:ring-2 focus:ring-brand-cyan/60 transition';

  return (
    <label className="block">
      <span className="block text-sm font-medium text-ink mb-1.5">
        {label}
        {required && <span className="text-rose-400"> *</span>}
      </span>
      {options ? (
        <select className={base} value={value ?? ''} onChange={(e) => onChange(e.target.value)}>
          <option value="">— choose —</option>
          {options.map((o) => (
            <option key={o.value ?? o} value={o.value ?? o}>{o.label ?? o}</option>
          ))}
        </select>
      ) : (
        <input
          className={base}
          type={type}
          value={value ?? ''}
          placeholder={placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {hint && <span className="block text-xs text-faint mt-1">{hint}</span>}
    </label>
  );
}

/* ── Panels ───────────────────────────────────────────────────────────────── */

export function Panel({ title, subtitle, children, action }) {
  return (
    <section className="card">
      {(title || action) && (
        <div className="flex items-start justify-between gap-4 mb-4">
          <div>
            {title && <h2 className="text-lg font-bold text-ink">{title}</h2>}
            {subtitle && <p className="text-sm text-muted mt-0.5">{subtitle}</p>}
          </div>
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

export function Empty({ icon: Icon, title, hint }) {
  return (
    <div className="text-center py-14">
      {Icon && <Icon size={40} className="mx-auto text-faint mb-3" />}
      <p className="text-ink font-semibold">{title}</p>
      {hint && <p className="text-sm text-muted mt-1 max-w-sm mx-auto">{hint}</p>}
    </div>
  );
}

/** A slide-over for editing one record. Full-screen on a phone. */
export function Drawer({ open, title, subtitle, onClose, children, footer }) {
  return (
    <AnimatePresence>
      {open && (
        <motion.div
          initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
          className="fixed inset-0 z-50 flex justify-end bg-black/50 backdrop-blur-sm"
          onClick={onClose}
        >
          <motion.div
            initial={{ x: 40, opacity: 0 }} animate={{ x: 0, opacity: 1 }} exit={{ x: 40, opacity: 0 }}
            transition={{ type: 'spring', stiffness: 320, damping: 32 }}
            onClick={(e) => e.stopPropagation()}
            className="glass-strong w-full sm:max-w-lg h-full flex flex-col"
          >
            <div className="flex items-start justify-between gap-4 p-5 border-b border-line/60">
              <div className="min-w-0">
                <h3 className="text-lg font-bold text-ink truncate">{title}</h3>
                {subtitle && <p className="text-sm text-muted truncate">{subtitle}</p>}
              </div>
              <button onClick={onClose} className="p-2 -m-2 text-muted hover:text-ink" aria-label="Close">
                <X size={22} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-4">{children}</div>
            {footer && <div className="p-5 border-t border-line/60">{footer}</div>}
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Small grey chip for a missing field — the "what's left" language. */
export function Missing({ fields }) {
  const LABELS = {
    profile: 'not linked yet',
    gr_no: 'GR Number',
    date_of_birth: 'Date of birth',
    gender: 'Gender',
    phone: 'Phone',
    employee_no: 'Employee Number',
    cnic: 'CNIC',
    joining_date: 'Joining date',
    designation: 'Designation',
  };
  if (!fields?.length) {
    return <span className="text-xs text-emerald-400 font-medium">Complete</span>;
  }
  return (
    <span className="text-xs text-amber-400">
      Needs: {fields.map((f) => LABELS[f] || f).join(', ')}
    </span>
  );
}
