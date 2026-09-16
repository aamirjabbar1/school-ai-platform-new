import { useEffect, useState } from 'react';
import { onlineClassAPI } from '../../services/api';
import { CheckCircle2, Download } from 'lucide-react';

// The register, as it was actually recorded: joined, rejoined, minutes, status.
// Nobody marked it by hand — it is assembled from the connection events of the
// class itself, which is also why it can show a student who dropped twice and
// still attended almost all of the lesson.
export default function AttendanceReport({ sessionId, onBack, ended }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    onlineClassAPI.attendance(sessionId)
      .then(({ data: payload }) => setData(payload))
      .catch((err) => setError(err?.response?.data?.detail || 'Could not load attendance.'));
  }, [sessionId]);

  const statusTone = {
    present: 'text-emerald-400', late: 'text-amber-400',
    partial: 'text-sky-400', absent: 'text-rose-400',
  };

  const exportCsv = () => {
    const rows = (data?.rows || []).filter((r) => r.role === 'student');
    const header = ['Student', 'Class', 'Section', 'Joined', 'Rejoins', 'Minutes', 'Percent', 'Status'];
    const lines = rows.map((r) => [
      r.user_name, r.class_name, r.section || '',
      r.first_join_at ? new Date(r.first_join_at).toLocaleTimeString() : '',
      r.rejoin_count, r.total_minutes, r.attendance_percent, r.status,
    ].map((v) => `"${String(v ?? '').replace(/"/g, '""')}"`).join(','));

    const blob = new Blob([[header.join(','), ...lines].join('\n')], { type: 'text/csv' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `attendance-${data?.session?.subject || 'class'}-${new Date().toISOString().slice(0, 10)}.csv`;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="min-h-screen bg-surface text-ink p-4 lg:p-8">
      <div className="max-w-3xl mx-auto">
        {ended && (
          <div className="card mb-5 flex items-center gap-3">
            <CheckCircle2 className="text-emerald-400" size={22} />
            <div>
              <div className="font-semibold">Class ended</div>
              <div className="text-sm text-muted">Attendance was recorded automatically.</div>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between mb-4 gap-2">
          <h1 className="font-display font-bold text-xl">Attendance</h1>
          <div className="flex gap-2">
            {data && (
              <button onClick={exportCsv} className="btn-secondary text-sm">
                <Download size={15} /> CSV
              </button>
            )}
            <button onClick={onBack} className="btn-secondary text-sm">Back</button>
          </div>
        </div>

        {error && <div className="card text-rose-400 text-sm">{error}</div>}
        {!data && !error && <div className="card text-muted text-sm">Loading…</div>}

        {data && (
          <>
            <div className="card mb-4">
              <div className="font-semibold">
                {data.session.subject} — {data.session.class_name}
                {data.session.section ? ` (${data.session.section})` : ''}
              </div>
              <div className="text-sm text-muted mt-1">
                {Math.round((data.session.duration_seconds || 0) / 60)} minute class ·{' '}
                {data.rows.filter((r) => r.role === 'student').length} students on the register
              </div>
            </div>

            <div className="card overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted">
                    <th className="py-2 pr-3 font-medium">Student</th>
                    <th className="py-2 pr-3 font-medium">Joined</th>
                    <th className="py-2 pr-3 font-medium">Minutes</th>
                    <th className="py-2 pr-3 font-medium">%</th>
                    <th className="py-2 font-medium">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.rows.filter((r) => r.role === 'student').map((row) => (
                    <tr key={row.id} className="border-t border-line/50">
                      <td className="py-2 pr-3">{row.user_name}</td>
                      <td className="py-2 pr-3 text-muted">
                        {row.first_join_at
                          ? new Date(row.first_join_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                          : '—'}
                        {row.rejoin_count > 0 && (
                          <span className="text-xs text-faint"> (+{row.rejoin_count} rejoin)</span>
                        )}
                      </td>
                      <td className="py-2 pr-3">{row.total_minutes}</td>
                      <td className="py-2 pr-3">{row.attendance_percent}%</td>
                      <td className={`py-2 font-semibold capitalize ${statusTone[row.status] || ''}`}>
                        {row.status}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
