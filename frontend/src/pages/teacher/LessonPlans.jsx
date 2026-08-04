import { useState, useEffect } from 'react';
import Layout from '../../components/Layout';
import { lessonPlanAPI } from '../../services/api';
import {
  CalendarRange, Wand2, Loader2, Eye, Trash2, Globe, EyeOff, X, Copy,
  FileText, FileType2, Printer,
} from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import { subjectsFor, classesFor, sectionsFor } from '../../constants/academics';

const PLAN_TYPES = [
  { value: 'daily',     label: 'Daily' },
  { value: 'weekly',    label: 'Weekly' },
  { value: 'monthly',   label: 'Monthly' },
  { value: 'date_wise', label: 'Date-wise' },
  { value: 'unit',      label: 'Unit-wise' },
  { value: 'chapter',   label: 'Chapter-wise' },
  { value: 'term',      label: 'Term-wise' },
  { value: 'annual',    label: 'Annual' },
  { value: 'revision',  label: 'Revision' },
  { value: 'exam_prep', label: 'Exam Preparation' },
  { value: 'practical', label: 'Practical / Lab' },
];
const BLOOM_LEVELS = ['', 'Remember', 'Understand', 'Apply', 'Analyze', 'Evaluate', 'Create'];

// Field groups mirror the backend PDF/Word export so all views show the same data.
const CELL_GROUPS = [
  { header: 'Topic', fields: [['chapter', 'Chapter'], ['topic', 'Topic'], ['subtopic', 'Subtopic']] },
  { header: 'Objectives & Outcomes', fields: [['objectives', 'Objectives'], ['outcomes', 'Outcomes'], ['prior_knowledge', 'Prior knowledge']] },
  { header: 'Methodology & Activities', fields: [['methodology', 'Method'], ['teacher_activities', 'Teacher'], ['student_activities', 'Students'], ['group_activity', 'Activity'], ['hots', 'HOTS']] },
  { header: 'Resources & Examples', fields: [['resources', 'Resources'], ['real_life_examples', 'Real-life'], ['differentiation', 'Differentiation']] },
  { header: 'Homework & Assessment', fields: [['classwork', 'Classwork'], ['homework', 'Homework'], ['assessment', 'Assessment'], ['remarks', 'Remarks']] },
];

const SUMMARY_LABELS = [
  ['academic_session', 'Academic Session'], ['subject', 'Subject'], ['grade', 'Grade'], ['board', 'Board'],
  ['total_chapters', 'Total Chapters'], ['total_weeks', 'Total Teaching Weeks'],
  ['total_teaching_days', 'Total Teaching Days'], ['total_lessons', 'Total Lessons'],
  ['total_practical_lessons', 'Total Practical Lessons'], ['total_assessments', 'Total Assessments'],
  ['total_homework', 'Total Homework'], ['revision_schedule', 'Revision Schedule'],
  ['exam_prep_schedule', 'Exam Preparation Schedule'], ['expected_completion_date', 'Expected Completion Date'],
];

const EMPTY_FORM = {
  subject: '', class_name: '', section: '', plan_type: 'weekly', board: '', book_name: '',
  academic_session: '', start_date: '', end_date: '', num_weeks: '', days_per_week: '', periods_per_week: '',
  chapters: '', topics: '', learning_objectives: '', bloom_level: '', methodology: '', resources: '',
  homework_pref: '', assessment_pref: '', holidays: '', exam_schedule: '', revision_week: '', teacher_notes: '',
};

const esc = (s) => String(s ?? '').replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));

// New plans are the 17-section LSS document; older saved plans only carry a
// `lessons[]` schedule and render with the legacy grid.
const isLssPlan = (pd) => !!(pd && (pd.learning_outcomes || pd.teaching_methodology || pd.weekly_plan));

const planCardMeta = (pd) => {
  if (!pd) return '';
  if (isLssPlan(pd)) return pd.cover?.chapter_topic || 'LSS lesson plan';
  const n = pd.lessons?.length || 0;
  return n > 0 ? `${n} lessons` : '';
};

const LSS_COVER_LABELS = [
  ['subject', 'Subject'], ['class_name', 'Class'], ['book_name', 'Book Name'], ['edition', 'Edition'],
  ['academic_session', 'Academic Session'], ['term', 'Term'], ['unit_number', 'Unit Number'],
  ['unit_title', 'Unit Title'], ['chapter_topic', 'Chapter / Topic'],
];
const LSS_DIFF_LABELS = [
  ['slow_learners', 'Slow Learners'], ['average_learners', 'Average Learners'], ['high_achievers', 'High Achievers'],
];
const toParas = (text) => String(text ?? '').split('\n').map((s) => s.trim()).filter(Boolean);


// Admin review state, shown read-only so teachers can see and act on feedback.
const REVIEW_BADGE = {
  pending:  { cls: 'badge-yellow', label: 'Awaiting review' },
  approved: { cls: 'badge-green',  label: 'Approved' },
  rejected: { cls: 'badge-red',    label: 'Changes requested' },
};

export default function LessonPlans() {
  const { user } = useAuth();
  const subjectOptions = subjectsFor(user);
  const classOptions = classesFor(user);

  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showGenerator, setShowGenerator] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState('');
  const [viewPlan, setViewPlan] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);

  useEffect(() => {
    lessonPlanAPI.getAll().then(({ data }) => setPlans(data)).finally(() => setLoading(false));
  }, []);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const generate = async () => {
    if (!form.subject || !form.class_name) {
      setError('Subject and class are required');
      return;
    }
    setGenerating(true);
    setError('');
    try {
      const toList = (s) => (s ? s.split(',').map((t) => t.trim()).filter(Boolean) : []);
      const toInt = (v) => (v === '' || v == null ? null : parseInt(v, 10));
      const { data } = await lessonPlanAPI.generate({
        ...form,
        chapters: toList(form.chapters),
        topics: toList(form.topics),
        num_weeks: toInt(form.num_weeks),
        days_per_week: toInt(form.days_per_week),
        periods_per_week: toInt(form.periods_per_week),
      });
      setPlans((prev) => [data.plan, ...prev]);
      setShowGenerator(false);
      setForm(EMPTY_FORM);
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to generate lesson plan. Please try again.');
    } finally {
      setGenerating(false);
    }
  };

  const togglePublish = async (id) => {
    try {
      const { data } = await lessonPlanAPI.togglePublish(id);
      setPlans((prev) => prev.map((p) => (p.id === id ? data.plan : p)));
    } catch (e) { console.error(e); }
  };

  const duplicate = async (id) => {
    try {
      const { data } = await lessonPlanAPI.duplicate(id);
      setPlans((prev) => [data, ...prev]);
    } catch (e) { console.error(e); }
  };

  const deletePlan = async (id) => {
    if (!confirm('Delete this lesson plan?')) return;
    await lessonPlanAPI.delete(id);
    setPlans((prev) => prev.filter((p) => p.id !== id));
    if (viewPlan?.id === id) setViewPlan(null);
  };

  const downloadBlob = (data, filename, type) => {
    const url = window.URL.createObjectURL(new Blob([data], { type }));
    const link = document.createElement('a');
    link.href = url;
    link.setAttribute('download', filename);
    document.body.appendChild(link);
    link.click();
    link.remove();
    window.URL.revokeObjectURL(url);
  };

  const exportPdf = async (plan) => {
    try {
      const { data } = await lessonPlanAPI.downloadPdf(plan.id);
      const safe = (plan.title || 'lesson_plan').replace(/[^a-z0-9_-]+/gi, '_');
      downloadBlob(data, `${safe}.pdf`, 'application/pdf');
    } catch (e) { setError('Failed to download PDF'); }
  };

  const exportDocx = async (plan) => {
    try {
      const { data } = await lessonPlanAPI.downloadDocx(plan.id);
      const safe = (plan.title || 'lesson_plan').replace(/[^a-z0-9_-]+/gi, '_');
      downloadBlob(data, `${safe}.docx`, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document');
    } catch (e) { setError('Failed to download Word document'); }
  };

  const printPlan = (plan) => {
    const win = window.open('', '_blank');
    if (!win) return;
    win.document.write(buildPrintHtml(plan));
    win.document.close();
    win.focus();
    win.onload = () => { win.print(); };
    setTimeout(() => { try { win.print(); } catch (_) {} }, 400);
  };

  return (
    <Layout title="Lesson Plans">
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="font-semibold text-ink">Lesson Plans</h2>
          <p className="text-sm text-muted">Generate AI-powered, curriculum-aligned teaching schedules</p>
        </div>
        <button onClick={() => setShowGenerator(true)} className="btn-primary flex items-center gap-2">
          <Wand2 size={16} /> Generate Lesson Plan
        </button>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-red-700 text-sm">
          <X size={16} /> {error}
          <button onClick={() => setError('')} className="ml-auto"><X size={14} /></button>
        </div>
      )}

      {loading ? (
        <div className="grid gap-3">{[1, 2, 3].map((i) => <div key={i} className="h-20 bg-surface-3 rounded-xl animate-pulse" />)}</div>
      ) : plans.length === 0 ? (
        <div className="card text-center py-12">
          <CalendarRange size={40} className="mx-auto mb-3 text-faint" />
          <p className="text-muted">No lesson plans yet</p>
          <button onClick={() => setShowGenerator(true)} className="btn-primary mt-3 inline-flex items-center gap-2">
            <Wand2 size={16} /> Generate First Plan
          </button>
        </div>
      ) : (
        <div className="grid gap-3">
          {plans.map((p) => {
            const cardMeta = planCardMeta(p.plan_data);
            return (
              <div key={p.id} className="card hover:shadow-md transition-shadow">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <h3 className="font-semibold text-ink text-sm">{p.title}</h3>
                      <span className={p.is_published ? 'badge-green' : 'badge-gray'}>{p.is_published ? 'Published' : 'Draft'}</span>
                      {p.review_status && p.review_status !== 'approved' && (
                        <span className={(REVIEW_BADGE[p.review_status] || REVIEW_BADGE.pending).cls}>
                          {(REVIEW_BADGE[p.review_status] || REVIEW_BADGE.pending).label}
                        </span>
                      )}
                      {p.review_status === 'approved' && <span className="badge-green">Approved</span>}
                      <span className="badge-blue capitalize">{p.plan_type?.replace('_', ' ')}</span>
                    </div>
                    <p className="text-xs text-muted mt-1">
                      {p.subject} • {p.class_name}{p.section ? ` - ${p.section}` : ''}
                      {p.board ? ` • ${p.board}` : ''}{cardMeta ? ` • ${cardMeta}` : ''}
                    </p>
                    <p className="text-xs text-faint">{new Date(p.created_at).toLocaleDateString()}</p>
                    {p.review_status === 'rejected' && p.review_note && (
                      <p className="text-xs text-red-600 mt-1">
                        <span className="font-medium">Admin feedback:</span> {p.review_note}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 shrink-0">
                    <button onClick={() => setViewPlan(p)} className="p-1.5 rounded-lg hover:bg-surface-3 text-muted hover:text-blue-600" title="View plan"><Eye size={16} /></button>
                    <button onClick={() => exportPdf(p)} className="p-1.5 rounded-lg hover:bg-surface-3 text-muted hover:text-indigo-600" title="Export PDF"><FileText size={16} /></button>
                    <button onClick={() => exportDocx(p)} className="p-1.5 rounded-lg hover:bg-surface-3 text-muted hover:text-sky-600" title="Export Word"><FileType2 size={16} /></button>
                    <button onClick={() => printPlan(p)} className="p-1.5 rounded-lg hover:bg-surface-3 text-muted hover:text-slate-600" title="Print"><Printer size={16} /></button>
                    <button onClick={() => duplicate(p.id)} className="p-1.5 rounded-lg hover:bg-surface-3 text-muted hover:text-purple-600" title="Duplicate"><Copy size={16} /></button>
                    <button onClick={() => togglePublish(p.id)} className={`p-1.5 rounded-lg hover:bg-surface-3 ${p.is_published ? 'text-green-600' : 'text-faint hover:text-green-600'}`} title={p.is_published ? 'Unpublish' : 'Publish'}>{p.is_published ? <Globe size={16} /> : <EyeOff size={16} />}</button>
                    <button onClick={() => deletePlan(p.id)} className="p-1.5 rounded-lg hover:bg-surface-3 text-faint hover:text-red-600" title="Delete"><Trash2 size={16} /></button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showGenerator && (
        <GeneratorModal
          form={form} set={set} user={user} subjectOptions={subjectOptions} classOptions={classOptions}
          generating={generating} onClose={() => setShowGenerator(false)} onGenerate={generate}
        />
      )}

      {viewPlan && (
        <ViewModal
          plan={viewPlan} onClose={() => setViewPlan(null)}
          onPdf={() => exportPdf(viewPlan)} onDocx={() => exportDocx(viewPlan)} onPrint={() => printPlan(viewPlan)}
        />
      )}
    </Layout>
  );
}

// ─── Generator modal ──────────────────────────────────────────────────────────

function GeneratorModal({ form, set, user, subjectOptions, classOptions, generating, onClose, onGenerate }) {
  const sections = sectionsFor(user, form.class_name);
  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto">
      <div className="bg-surface rounded-2xl shadow-xl w-full max-w-2xl my-4">
        <div className="p-5 border-b flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Wand2 size={18} className="text-emerald-600" />
            <h2 className="font-bold text-ink">Generate Lesson Plan</h2>
          </div>
          <button onClick={onClose} className="text-faint hover:text-muted"><X size={20} /></button>
        </div>
        <div className="p-5 space-y-5 max-h-[75vh] overflow-y-auto">
          {/* Basics */}
          <Section title="Basics">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Subject *">
                <select value={form.subject} onChange={(e) => set('subject', e.target.value)} className="input-field">
                  <option value="">Select</option>
                  {subjectOptions.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </Field>
              <Field label="Class *">
                <select value={form.class_name} onChange={(e) => { set('class_name', e.target.value); set('section', ''); }} className="input-field">
                  <option value="">Select</option>
                  {classOptions.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </Field>
              {form.class_name && (
                <Field label="Section">
                  {sections.length > 0 ? (
                    <select value={form.section} onChange={(e) => set('section', e.target.value)} className="input-field">
                      <option value="">Whole class</option>
                      {sections.map((s) => <option key={s} value={s}>{s}</option>)}
                    </select>
                  ) : (
                    <input type="text" value={form.section} onChange={(e) => set('section', e.target.value)} className="input-field" placeholder="Optional (e.g. A)" />
                  )}
                </Field>
              )}
              <Field label="Plan Type">
                <select value={form.plan_type} onChange={(e) => set('plan_type', e.target.value)} className="input-field">
                  {PLAN_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                </select>
              </Field>
              <Field label="Board / Curriculum">
                <input type="text" value={form.board} onChange={(e) => set('board', e.target.value)} className="input-field" placeholder="e.g. Federal Board, Cambridge" />
              </Field>
              <Field label="Book Name">
                <input type="text" value={form.book_name} onChange={(e) => set('book_name', e.target.value)} className="input-field" placeholder="Optional" />
              </Field>
            </div>
          </Section>

          {/* Schedule */}
          <Section title="Schedule">
            <div className="grid grid-cols-3 gap-3">
              <Field label="Academic Session"><input type="text" value={form.academic_session} onChange={(e) => set('academic_session', e.target.value)} className="input-field" placeholder="2025-2026" /></Field>
              <Field label="Start Date"><input type="text" value={form.start_date} onChange={(e) => set('start_date', e.target.value)} className="input-field" placeholder="e.g. 5 Aug 2025" /></Field>
              <Field label="End Date"><input type="text" value={form.end_date} onChange={(e) => set('end_date', e.target.value)} className="input-field" placeholder="e.g. 20 Dec 2025" /></Field>
              <Field label="Teaching Weeks"><input type="number" min="1" value={form.num_weeks} onChange={(e) => set('num_weeks', e.target.value)} className="input-field" /></Field>
              <Field label="Days / Week"><input type="number" min="1" max="7" value={form.days_per_week} onChange={(e) => set('days_per_week', e.target.value)} className="input-field" /></Field>
              <Field label="Periods / Week"><input type="number" min="1" value={form.periods_per_week} onChange={(e) => set('periods_per_week', e.target.value)} className="input-field" /></Field>
            </div>
          </Section>

          {/* Content */}
          <Section title="Content">
            <Field label="Chapters / Units (comma-separated)"><input type="text" value={form.chapters} onChange={(e) => set('chapters', e.target.value)} className="input-field" placeholder="e.g. Cell Biology, Genetics, Evolution" /></Field>
            <Field label="Topics / Subtopics (comma-separated)"><input type="text" value={form.topics} onChange={(e) => set('topics', e.target.value)} className="input-field" placeholder="Optional" /></Field>
          </Section>

          {/* Pedagogy */}
          <Section title="Pedagogy">
            <Field label="Learning Objectives"><textarea rows={2} value={form.learning_objectives} onChange={(e) => set('learning_objectives', e.target.value)} className="input-field" placeholder="Optional — the AI will fill sensible objectives if left blank" /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Bloom's Level">
                <select value={form.bloom_level} onChange={(e) => set('bloom_level', e.target.value)} className="input-field">
                  {BLOOM_LEVELS.map((b) => <option key={b} value={b}>{b || 'Any'}</option>)}
                </select>
              </Field>
              <Field label="Teaching Methodology"><input type="text" value={form.methodology} onChange={(e) => set('methodology', e.target.value)} className="input-field" placeholder="e.g. Inquiry-based, lecture+activity" /></Field>
            </div>
            <Field label="Teaching Resources"><input type="text" value={form.resources} onChange={(e) => set('resources', e.target.value)} className="input-field" placeholder="e.g. Smartboard, models, videos" /></Field>
          </Section>

          {/* Assessment & extras */}
          <Section title="Assessment & Calendar">
            <div className="p-2.5 mb-1 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-800">
              The AI automatically follows the school's uploaded <strong>Academic Calendar</strong> and any
              <strong> Official Notices / Emergency Updates</strong> (holidays, exams, revision weeks, vacations).
              The fields below are optional extra hints.
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Homework Preference"><input type="text" value={form.homework_pref} onChange={(e) => set('homework_pref', e.target.value)} className="input-field" placeholder="e.g. After every lesson" /></Field>
              <Field label="Assessment Preference"><input type="text" value={form.assessment_pref} onChange={(e) => set('assessment_pref', e.target.value)} className="input-field" placeholder="e.g. Weekly quiz, unit tests" /></Field>
              <Field label="Holidays"><input type="text" value={form.holidays} onChange={(e) => set('holidays', e.target.value)} className="input-field" placeholder="e.g. 14 Aug, 2 weeks winter break" /></Field>
              <Field label="Exam Schedule"><input type="text" value={form.exam_schedule} onChange={(e) => set('exam_schedule', e.target.value)} className="input-field" placeholder="e.g. Mid-term week 8" /></Field>
              <Field label="Revision Week"><input type="text" value={form.revision_week} onChange={(e) => set('revision_week', e.target.value)} className="input-field" placeholder="e.g. Last week before exam" /></Field>
            </div>
            <Field label="Teacher Notes"><textarea rows={2} value={form.teacher_notes} onChange={(e) => set('teacher_notes', e.target.value)} className="input-field" placeholder="Any extra instructions for the AI" /></Field>
          </Section>

          <div className="flex gap-3 pt-1">
            <button onClick={onClose} className="btn-secondary flex-1">Cancel</button>
            <button onClick={onGenerate} disabled={generating} className="btn-primary flex-1 flex items-center justify-center gap-2">
              {generating ? <Loader2 size={16} className="animate-spin" /> : <Wand2 size={16} />}
              {generating ? 'Generating…' : 'Generate'}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── View modal ───────────────────────────────────────────────────────────────

function ViewModal({ plan, onClose, onPdf, onDocx, onPrint }) {
  const pd = plan.plan_data || {};
  const lss = isLssPlan(pd);
  const subtitle = lss
    ? (pd.cover?.chapter_topic || '17-section lesson plan')
    : `${pd.lessons?.length || 0} lessons`;

  return (
    <div className="fixed inset-0 bg-black/50 z-50 flex items-start justify-center p-4 overflow-y-auto">
      <div className={`bg-surface rounded-2xl shadow-xl w-full ${lss ? 'max-w-4xl' : 'max-w-6xl'} my-4`}>
        <div className="p-5 border-b flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="font-bold text-ink truncate">{plan.title}</h2>
            <p className="text-sm text-muted">
              {plan.subject} • {plan.class_name}{plan.section ? ` - ${plan.section}` : ''}
              {plan.board ? ` • ${plan.board}` : ''} • {subtitle}
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button onClick={onPdf} className="btn-secondary flex items-center gap-1.5 text-sm"><FileText size={14} /> PDF</button>
            <button onClick={onDocx} className="btn-secondary flex items-center gap-1.5 text-sm"><FileType2 size={14} /> Word</button>
            <button onClick={onPrint} className="btn-secondary flex items-center gap-1.5 text-sm"><Printer size={14} /> Print</button>
            <button onClick={onClose} className="text-faint hover:text-muted"><X size={20} /></button>
          </div>
        </div>
        <div className="p-5 space-y-3 max-h-[75vh] overflow-y-auto">
          {lss ? <LssPlanView pd={pd} /> : <LegacyPlanBody pd={pd} />}
        </div>
      </div>
    </div>
  );
}

// ─── LSS 17-section document view ─────────────────────────────────────────────

function SecHead({ n, title }) {
  return (
    <h3 className="mt-4 mb-2 px-3 py-1.5 rounded-md bg-slate-800 text-white text-sm font-semibold">
      {n}. {title}
    </h3>
  );
}

function SubHead({ children }) {
  return <p className="mt-2 mb-1 text-sm font-semibold text-blue-800">{children}</p>;
}

function Paras({ text }) {
  return toParas(text).map((s, i) => <p key={i} className="text-sm text-muted mb-1.5 leading-relaxed">{s}</p>);
}

function Bullets({ items, numbered }) {
  const list = (items || []).filter(Boolean);
  if (list.length === 0) return null;
  const Tag = numbered ? 'ol' : 'ul';
  return (
    <Tag className={`${numbered ? 'list-decimal' : 'list-disc'} pl-6 space-y-1 text-sm text-muted`}>
      {list.map((it, i) => <li key={i} className="leading-relaxed">{it}</li>)}
    </Tag>
  );
}

function DocTable({ headers, rows, widths }) {
  return (
    <div className="overflow-x-auto border border-line rounded-lg">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-slate-800 text-white">
            {headers.map((h, i) => (
              <th key={h} className="p-2 text-left font-semibold" style={widths ? { width: widths[i] } : undefined}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className={i % 2 ? 'bg-surface-2' : ''}>
              {r.map((c, j) => <td key={j} className="p-2 align-top border-t border-line text-muted">{c}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LssPlanView({ pd }) {
  const cover = pd.cover || {};
  const wrap = pd.wrap_up || {};
  const diff = pd.differentiation || {};
  const coverRows = LSS_COVER_LABELS.filter(([k]) => cover[k]);

  return (
    <div>
      {coverRows.length > 0 && (
        <>
          <SecHead n={1} title="Cover Page" />
          <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1 text-sm">
            {coverRows.map(([k, label]) => (
              <div key={k} className="flex gap-2 border-b border-line/60 py-1">
                <span className="font-medium text-ink/80 min-w-[130px]">{label}</span>
                <span className="text-muted">{cover[k]}</span>
              </div>
            ))}
          </div>
        </>
      )}

      {pd.learning_outcomes?.length > 0 && (
        <>
          <SecHead n={2} title="Students Learning Outcomes" />
          <p className="text-sm font-medium text-ink/90 mb-1">Students will be able to:</p>
          <Bullets items={pd.learning_outcomes} numbered />
        </>
      )}

      {pd.starter_activity && (<><SecHead n={3} title="Starter Activity" /><Paras text={pd.starter_activity} /></>)}

      {pd.brainstorming_questions?.length > 0 && (
        <><SecHead n={4} title="Brainstorming Questions" /><Bullets items={pd.brainstorming_questions} /></>
      )}

      {pd.teaching_methodology?.length > 0 && (
        <>
          <SecHead n={5} title="Teaching Methodology" />
          {pd.teaching_methodology.map((s, i) => (
            <div key={i}>
              {s?.heading && <SubHead>{s.heading}</SubHead>}
              <Paras text={s?.detail ?? s} />
            </div>
          ))}
        </>
      )}

      {pd.guided_practice && (<><SecHead n={6} title="Guided Practice" /><Paras text={pd.guided_practice} /></>)}
      {pd.independent_practice && (<><SecHead n={7} title="Independent Practice" /><Paras text={pd.independent_practice} /></>)}

      {(wrap.revision_questions?.length > 0 || wrap.oral_recap || wrap.quick_review) && (
        <>
          <SecHead n={8} title="Wrap-up" />
          {wrap.revision_questions?.length > 0 && (<><SubHead>Revision Questions</SubHead><Bullets items={wrap.revision_questions} /></>)}
          {wrap.oral_recap && (<><SubHead>Oral Recap</SubHead><Paras text={wrap.oral_recap} /></>)}
          {wrap.quick_review && (<><SubHead>Quick Classroom Review</SubHead><Paras text={wrap.quick_review} /></>)}
        </>
      )}

      {pd.resources?.length > 0 && (<><SecHead n={9} title="Resources Required" /><Bullets items={pd.resources} /></>)}
      {pd.assessment?.length > 0 && (<><SecHead n={10} title="Assessment" /><Bullets items={pd.assessment} /></>)}

      {pd.weekly_plan?.length > 0 && (
        <>
          <SecHead n={11} title="Week-wise Planning" />
          <DocTable
            headers={['Day', 'Classwork', 'Homework']}
            widths={['15%', '48%', '37%']}
            rows={pd.weekly_plan.map((d) => [d.day, d.classwork, d.homework])}
          />
        </>
      )}

      {pd.vocabulary?.length > 0 && (
        <>
          <SecHead n={12} title="Vocabulary" />
          <DocTable headers={['Word', 'Meaning']} widths={['28%', '72%']} rows={pd.vocabulary.map((v) => [v.word, v.meaning])} />
        </>
      )}

      {pd.qa?.length > 0 && (
        <>
          <SecHead n={13} title="Question / Answers" />
          {pd.qa.map((q, i) => (
            <div key={i} className="mb-2">
              <p className="text-sm font-semibold text-ink/90">Q{i + 1}. {q.question}</p>
              <p className="text-sm text-muted leading-relaxed"><span className="font-semibold">Ans.</span> {q.answer}</p>
            </div>
          ))}
        </>
      )}

      {pd.worksheets?.length > 0 && (
        <>
          <SecHead n={14} title="Worksheets" />
          {pd.worksheets.map((ws, i) => (
            <div key={i}>
              {ws?.type && <SubHead>{ws.type}</SubHead>}
              <Bullets items={ws?.items || (typeof ws === 'string' ? [ws] : [])} />
            </div>
          ))}
        </>
      )}

      {(diff.slow_learners || diff.average_learners || diff.high_achievers) && (
        <>
          <SecHead n={15} title="Differentiated Instruction" />
          {LSS_DIFF_LABELS.filter(([k]) => diff[k]).map(([k, label]) => (
            <div key={k}><SubHead>{label}</SubHead><Paras text={diff[k]} /></div>
          ))}
        </>
      )}

      {pd.cross_curricular?.length > 0 && (
        <>
          <SecHead n={16} title="Cross-Curricular Links" />
          <DocTable headers={['Subject', 'Connection']} widths={['26%', '74%']} rows={pd.cross_curricular.map((c) => [c.subject, c.connection])} />
        </>
      )}

      {pd.values?.length > 0 && (<><SecHead n={17} title="Values & Life Skills" /><Bullets items={pd.values} /></>)}
    </div>
  );
}

// ─── Legacy schedule grid view ────────────────────────────────────────────────

function LegacyPlanBody({ pd }) {
  const lessons = pd.lessons || [];
  const summary = pd.summary || {};
  const overview = pd.overview;
  const cell = (ls, fields) => fields
    .filter(([k]) => ls[k])
    .map(([k, label]) => <div key={k} className="mb-0.5"><span className="font-semibold">{label}:</span> {ls[k]}</div>);

  return (
    <>
      {overview && <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-sm text-blue-800">{overview}</div>}

      {lessons.length === 0 ? (
        <p className="text-muted text-center py-4">No lessons in this plan.</p>
      ) : (
        <div className="overflow-x-auto border border-line rounded-lg">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="bg-slate-800 text-white">
                <th className="p-2 text-left font-semibold min-w-[90px]">Wk / Date</th>
                {CELL_GROUPS.map((g) => <th key={g.header} className="p-2 text-left font-semibold min-w-[160px]">{g.header}</th>)}
              </tr>
            </thead>
            <tbody>
              {lessons.map((ls, i) => (
                <tr key={i} className={i % 2 ? 'bg-surface-2' : ''}>
                  <td className="p-2 align-top border-t border-line font-semibold whitespace-nowrap">
                    {ls.week != null && <div>Week {ls.week}</div>}
                    {ls.dates && <div className="font-normal text-muted">{ls.dates}</div>}
                    {ls.day && <div className="font-normal text-muted">{ls.day}</div>}
                    {ls.period && <div className="font-normal text-muted">P{ls.period}</div>}
                  </td>
                  {CELL_GROUPS.map((g) => <td key={g.header} className="p-2 align-top border-t border-line text-muted">{cell(ls, g.fields)}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {Object.keys(summary).length > 0 && (
        <div>
          <h3 className="font-semibold text-ink mb-2">Plan Summary</h3>
          <div className="grid sm:grid-cols-2 gap-x-6 gap-y-1.5 text-sm">
            {SUMMARY_LABELS.filter(([k]) => summary[k] != null && summary[k] !== '').map(([k, label]) => (
              <div key={k} className="flex gap-2 border-b border-line/60 py-1">
                <span className="font-medium text-ink/80 min-w-[170px]">{label}</span>
                <span className="text-muted">{summary[k]}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </>
  );
}

// ─── Small layout helpers ───────────────────────────────────────────────────

function Section({ title, children }) {
  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-wide text-faint mb-2">{title}</h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <div>
      <label className="block text-sm font-medium text-ink/90 mb-1">{label}</label>
      {children}
    </div>
  );
}

// ─── Print document (standalone window) ───────────────────────────────────────

function buildPrintHtml(plan) {
  return isLssPlan(plan.plan_data || {}) ? buildLssPrintHtml(plan) : buildLegacyPrintHtml(plan);
}

function buildLssPrintHtml(plan) {
  const pd = plan.plan_data || {};
  const cover = pd.cover || {};
  const wrap = pd.wrap_up || {};
  const diff = pd.differentiation || {};
  const metaBits = [plan.subject, plan.class_name, plan.section && `Section ${plan.section}`, plan.board,
    plan.plan_type && `${plan.plan_type.replace('_', ' ')} plan`]
    .filter(Boolean).map(esc).join(' • ');

  const sec = (n, title) => `<h2 class="sec">${n}. ${esc(title)}</h2>`;
  const paras = (t) => toParas(t).map((s) => `<p>${esc(s)}</p>`).join('');
  const list = (items, ordered) => {
    const li = (items || []).filter(Boolean).map((it) => `<li>${esc(it)}</li>`).join('');
    return li ? `<${ordered ? 'ol' : 'ul'}>${li}</${ordered ? 'ol' : 'ul'}>` : '';
  };
  const table = (headers, rows, widths) => {
    const head = headers.map((h, i) => `<th${widths ? ` style="width:${widths[i]}"` : ''}>${esc(h)}</th>`).join('');
    const body = rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('');
    return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
  };

  const parts = [];
  const coverRows = LSS_COVER_LABELS.filter(([k]) => cover[k]);
  if (coverRows.length) {
    const body = coverRows.map(([k, label]) => `<tr><th class="kv">${esc(label)}</th><td>${esc(cover[k])}</td></tr>`).join('');
    parts.push(sec(1, 'Cover Page'), `<table class="kv"><tbody>${body}</tbody></table>`);
  }
  if (pd.learning_outcomes?.length) { parts.push(sec(2, 'Students Learning Outcomes'), '<p><strong>Students will be able to:</strong></p>', list(pd.learning_outcomes, true)); }
  if (pd.starter_activity) parts.push(sec(3, 'Starter Activity'), paras(pd.starter_activity));
  if (pd.brainstorming_questions?.length) parts.push(sec(4, 'Brainstorming Questions'), list(pd.brainstorming_questions));
  if (pd.teaching_methodology?.length) {
    parts.push(sec(5, 'Teaching Methodology'));
    pd.teaching_methodology.forEach((s) => {
      if (s?.heading) parts.push(`<h3 class="sub">${esc(s.heading)}</h3>`);
      parts.push(paras(s?.detail ?? s));
    });
  }
  if (pd.guided_practice) parts.push(sec(6, 'Guided Practice'), paras(pd.guided_practice));
  if (pd.independent_practice) parts.push(sec(7, 'Independent Practice'), paras(pd.independent_practice));
  if (wrap.revision_questions?.length || wrap.oral_recap || wrap.quick_review) {
    parts.push(sec(8, 'Wrap-up'));
    if (wrap.revision_questions?.length) parts.push('<h3 class="sub">Revision Questions</h3>', list(wrap.revision_questions));
    if (wrap.oral_recap) parts.push('<h3 class="sub">Oral Recap</h3>', paras(wrap.oral_recap));
    if (wrap.quick_review) parts.push('<h3 class="sub">Quick Classroom Review</h3>', paras(wrap.quick_review));
  }
  if (pd.resources?.length) parts.push(sec(9, 'Resources Required'), list(pd.resources));
  if (pd.assessment?.length) parts.push(sec(10, 'Assessment'), list(pd.assessment));
  if (pd.weekly_plan?.length) parts.push(sec(11, 'Week-wise Planning'), table(['Day', 'Classwork', 'Homework'], pd.weekly_plan.map((d) => [d.day, d.classwork, d.homework]), ['15%', '48%', '37%']));
  if (pd.vocabulary?.length) parts.push(sec(12, 'Vocabulary'), table(['Word', 'Meaning'], pd.vocabulary.map((v) => [v.word, v.meaning]), ['28%', '72%']));
  if (pd.qa?.length) {
    parts.push(sec(13, 'Question / Answers'));
    pd.qa.forEach((q, i) => parts.push(`<p class="q"><strong>Q${i + 1}. ${esc(q.question)}</strong></p><p class="a"><strong>Ans.</strong> ${esc(q.answer)}</p>`));
  }
  if (pd.worksheets?.length) {
    parts.push(sec(14, 'Worksheets'));
    pd.worksheets.forEach((ws) => {
      if (ws?.type) parts.push(`<h3 class="sub">${esc(ws.type)}</h3>`);
      parts.push(list(ws?.items || (typeof ws === 'string' ? [ws] : [])));
    });
  }
  if (diff.slow_learners || diff.average_learners || diff.high_achievers) {
    parts.push(sec(15, 'Differentiated Instruction'));
    LSS_DIFF_LABELS.filter(([k]) => diff[k]).forEach(([k, label]) => parts.push(`<h3 class="sub">${esc(label)}</h3>`, paras(diff[k])));
  }
  if (pd.cross_curricular?.length) parts.push(sec(16, 'Cross-Curricular Links'), table(['Subject', 'Connection'], pd.cross_curricular.map((c) => [c.subject, c.connection]), ['26%', '74%']));
  if (pd.values?.length) parts.push(sec(17, 'Values & Life Skills'), list(pd.values));

  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(plan.title)}</title>
<style>
  @page { size: A4 portrait; margin: 16mm; }
  * { box-sizing: border-box; }
  body { font-family: Arial, Helvetica, sans-serif; color: #111827; margin: 0; font-size: 12px; line-height: 1.5; }
  h1 { font-size: 20px; margin: 0 0 2px; text-align: center; }
  .meta { text-align: center; color: #6b7280; font-size: 11px; margin-bottom: 14px; }
  h2.sec { background: #1e3a8a; color: #fff; font-size: 13px; padding: 5px 8px; border-radius: 3px; margin: 16px 0 8px; page-break-after: avoid; }
  h3.sub { color: #1e3a8a; font-size: 12px; margin: 8px 0 3px; page-break-after: avoid; }
  p { margin: 0 0 6px; }
  p.a { margin-bottom: 10px; }
  ul, ol { margin: 0 0 8px; padding-left: 22px; }
  li { margin-bottom: 3px; }
  table { width: 100%; border-collapse: collapse; margin: 4px 0 10px; }
  th, td { border: 0.5px solid #d1d5db; padding: 5px 7px; font-size: 11px; text-align: left; vertical-align: top; }
  thead th { background: #1e3a8a; color: #fff; }
  tbody tr:nth-child(even) { background: #f8fafc; }
  table.kv tbody tr:nth-child(even) { background: transparent; }
  th.kv { background: #f3f4f6; color: #111827; width: 180px; }
</style></head><body>
  <h1>${esc(pd.title || plan.title)}</h1>
  <div class="meta">${metaBits}</div>
  ${parts.join('\n')}
</body></html>`;
}

function buildLegacyPrintHtml(plan) {
  const lessons = plan.plan_data?.lessons || [];
  const summary = plan.plan_data?.summary || {};
  const overview = plan.plan_data?.overview || '';
  const metaBits = [plan.subject, plan.class_name, plan.section && `Section ${plan.section}`, plan.board,
    plan.plan_type && `${plan.plan_type.replace('_', ' ')} plan`, plan.academic_session && `Session ${plan.academic_session}`]
    .filter(Boolean).map(esc).join(' • ');

  const cellHtml = (ls, fields) => fields.filter(([k]) => ls[k])
    .map(([k, label]) => `<div><strong>${esc(label)}:</strong> ${esc(ls[k])}</div>`).join('') || '&nbsp;';

  const rows = lessons.map((ls) => {
    const wk = [ls.week != null ? `<strong>Week ${esc(ls.week)}</strong>` : '', ls.dates && esc(ls.dates), ls.day && esc(ls.day), ls.period && `P${esc(ls.period)}`].filter(Boolean).join('<br/>');
    const cells = CELL_GROUPS.map((g) => `<td>${cellHtml(ls, g.fields)}</td>`).join('');
    return `<tr><td>${wk || '&nbsp;'}</td>${cells}</tr>`;
  }).join('');

  const headerCells = ['Wk / Date', ...CELL_GROUPS.map((g) => g.header)].map((h) => `<th>${esc(h)}</th>`).join('');

  const summaryRows = SUMMARY_LABELS.filter(([k]) => summary[k] != null && summary[k] !== '')
    .map(([k, label]) => `<tr><th>${esc(label)}</th><td>${esc(summary[k])}</td></tr>`).join('');

  return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(plan.title)}</title>
<style>
  @page { size: A4 landscape; margin: 12mm; }
  * { box-sizing: border-box; }
  body { font-family: Arial, Helvetica, sans-serif; color: #111827; margin: 0; }
  h1 { font-size: 18px; margin: 0 0 2px; text-align: center; }
  .meta { text-align: center; color: #6b7280; font-size: 11px; margin-bottom: 10px; }
  .overview { background: #f3f4f6; padding: 8px; border-radius: 4px; font-size: 11px; margin-bottom: 12px; }
  table { width: 100%; border-collapse: collapse; table-layout: fixed; }
  th, td { border: 0.5px solid #d1d5db; padding: 4px 5px; font-size: 8px; text-align: left; vertical-align: top; word-wrap: break-word; }
  thead th { background: #1e3a8a; color: #fff; font-size: 8.5px; }
  tbody tr:nth-child(even) { background: #f8fafc; }
  .summary { margin-top: 18px; }
  .summary h2 { font-size: 14px; color: #1e3a8a; }
  .summary table { table-layout: auto; }
  .summary th { background: #f3f4f6; width: 220px; font-size: 9.5px; }
  .summary td { font-size: 9.5px; }
</style></head><body>
  <h1>${esc(plan.title)}</h1>
  <div class="meta">${metaBits}</div>
  ${overview ? `<div class="overview">${esc(overview)}</div>` : ''}
  <table><thead><tr>${headerCells}</tr></thead><tbody>${rows || ''}</tbody></table>
  ${summaryRows ? `<div class="summary"><h2>Plan Summary</h2><table>${summaryRows}</table></div>` : ''}
</body></html>`;
}
