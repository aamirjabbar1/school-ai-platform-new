// ─── Centralised academic master lists ───────────────────────────────────────
//
// Single source of truth for subjects, classes and sections across the whole
// app. Add a subject/class here once and it appears everywhere automatically
// (Knowledge Base, Manage Users, Create Assignment, Question Papers, AI
// Assistant, Practice, and any future module).

// Master Subject List — the teaching subjects available system-wide.
export const SUBJECTS = [
  'Mathematics', 'General Mathematics (Humanities Group)', 'Science', 'General Science',
  'English', 'Urdu', 'Islamiat', 'Translation of Holy Quran', 'Computer Science',
  'Physics', 'Chemistry', 'Biology', 'Social Studies', 'History', 'Geography',
  'General Knowledge', 'Civics', 'Economics', 'Education',
];

// Knowledge Base also keeps a catch-all bucket for uploaded documents.
export const KB_SUBJECTS = [...SUBJECTS, 'Other'];

// Classes a student can belong to / be taught (used by academic modules).
export const CLASSES = [
  'Pre-Nursery', 'Nursery', 'KG',
  'Class 1', 'Class 2', 'Class 3', 'Class 4', 'Class 5', 'Class 6',
  'Class 7', 'Class 8', 'Class 9', 'Class 10', 'Class 11', 'Class 12',
];

// Knowledge Base documents can target "All Classes" plus the numbered classes.
export const CLASS_LEVELS = [
  'All Classes', 'Class 1', 'Class 2', 'Class 3', 'Class 4', 'Class 5', 'Class 6',
  'Class 7', 'Class 8', 'Class 9', 'Class 10', 'Class 11', 'Class 12',
];

// Classes offered when assigning to teachers (their own "Grade" vocabulary).
export const TEACHER_CLASSES = [
  'Pre-Nursery', 'Nursery', 'KG', 'Grade 1', 'Grade 2', 'Grade 3', 'Grade 4',
  'Grade 5', 'Grade 6', 'Grade 7', 'Grade 8', 'Grade 9', 'Grade 10',
];

// ─── Section helpers (mirror backend normalize_section) ────────────────────────

// Normalize a section value: strip a leading "Section"/"Sec" word, collapse
// spaces, upper-case short codes ("a" → "A"); keep longer names as typed.
export const normalizeSection = (raw) => {
  if (raw == null) return '';
  let s = String(raw).trim();
  if (!s) return '';
  s = s.replace(/^(section|sec)\b[\s:.\-]*/i, '').trim();
  s = s.replace(/\s+/g, ' ');
  if (!s) return '';
  return s.length <= 3 ? s.toUpperCase() : s;
};

// Parse a comma-separated section list into a deduped, normalized array.
export const parseSections = (raw) => {
  const out = [];
  String(raw || '').split(',').forEach((tok) => {
    const sec = normalizeSection(tok);
    if (sec && !out.includes(sec)) out.push(sec);
  });
  return out;
};

// ─── Class matching ───────────────────────────────────────────────────────────

// Map any class label to a comparable key so "Grade 5", "Class 5" and "5" match.
// Pre-primary levels key by name. Lets teacher assignments (which use "Grade N")
// line up with the "Class N" vocabulary used everywhere else.
export const classKey = (c) => {
  if (!c) return '';
  const s = String(c).trim().toLowerCase();
  if (s.includes('pre') && s.includes('nursery')) return 'pre-nursery';
  if (s === 'nursery') return 'nursery';
  if (s.startsWith('kg') || s.includes('kindergarten') || s === 'prep') return 'kg';
  const m = s.match(/(\d{1,2})/);
  if (m) return `c${parseInt(m[1], 10)}`;
  return s;
};

// ─── Teacher-permission filtering ─────────────────────────────────────────────
//
// These return the master list for non-teachers (and as a safe fallback for
// teachers who have nothing assigned yet, so they are never locked out). When a
// teacher HAS assignments, the lists are restricted to exactly those.

export const subjectsFor = (user, master = SUBJECTS) => {
  if (!user || user.role !== 'teacher') return master;
  const assigned = user.subjects || [];
  if (!assigned.length) return master;
  const set = new Set(assigned);
  const filtered = master.filter((s) => set.has(s));
  return filtered.length ? filtered : master;
};

export const classesFor = (user, master = CLASSES) => {
  if (!user || user.role !== 'teacher') return master;
  const assigned = user.assigned_classes || [];
  if (!assigned.length) return master;
  const keys = new Set(assigned.map(classKey));
  const filtered = master.filter((c) => keys.has(classKey(c)));
  return filtered.length ? filtered : master;
};

// Section names a teacher handles for a given class (from assigned_sections,
// which store "Grade 5 - A" combos). Empty array → no configured sections.
export const sectionsFor = (user, selectedClass) => {
  if (!user || user.role !== 'teacher' || !selectedClass) return [];
  const combos = user.assigned_sections || [];
  const key = classKey(selectedClass);
  const out = [];
  combos.forEach((combo) => {
    const idx = combo.indexOf(' - ');
    if (idx === -1) return;
    if (classKey(combo.slice(0, idx)) === key) {
      const sec = combo.slice(idx + 3).trim();
      if (sec && !out.includes(sec)) out.push(sec);
    }
  });
  return out;
};
