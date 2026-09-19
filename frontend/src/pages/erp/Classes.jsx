/**
 * Classes and sections.
 *
 * Read-only on purpose in this phase. The classes here were derived from the
 * classes the school is already teaching, and the fastest way to lose trust in
 * a new system is to let someone rename a class on day one and watch a
 * dashboard change.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Empty, Note, Panel } from '../../components/erp/Kit';
import { Building2, Users } from 'lucide-react';

const LEVEL_LABEL = {
  pre_primary: 'Pre-primary',
  primary: 'Primary',
  middle: 'Middle',
  secondary: 'Secondary',
  other: 'Other',
};

export default function ErpClasses() {
  const [loading, setLoading] = useState(true);
  const [classes, setClasses] = useState([]);
  const [session, setSession] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    (async () => {
      try {
        const [{ data: cls }, { data: st }] = await Promise.all([erpAPI.classes(), erpAPI.status()]);
        setClasses(cls);
        setSession(st.session);
      } catch (e) {
        setError(e.response?.data?.detail || 'Could not load classes.');
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) return <Layout title="Classes & sections"><Busy /></Layout>;

  return (
    <Layout title="Classes & sections">
      <div className="space-y-4 max-w-4xl">
        {error && <Note kind="bad">{error}</Note>}
        {session && (
          <p className="text-sm text-muted px-1">
            Session <strong className="text-ink">{session.name}</strong> · {classes.length} classes
          </p>
        )}

        {classes.length === 0 ? (
          <Empty icon={Building2} title="No classes yet"
                 hint="Run setup from the ERP home page and your classes will appear here." />
        ) : (
          <div className="space-y-3">
            {classes.map((c) => (
              <Panel key={c.id}>
                <div className="flex items-center justify-between gap-4">
                  <div className="min-w-0">
                    <h3 className="font-bold text-ink text-lg">{c.canonical_name}</h3>
                    <p className="text-sm text-muted">{LEVEL_LABEL[c.level] || c.level}</p>
                  </div>
                  <div className="flex items-center gap-2 text-ink shrink-0">
                    <Users size={18} className="text-brand-cyan" />
                    <span className="text-xl font-bold">{c.students}</span>
                  </div>
                </div>

                {c.sections.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-4">
                    {c.sections.map((s) => (
                      <span key={s.id} className="px-3 py-1.5 rounded-xl bg-surface-2 text-sm text-ink">
                        {s.name} <span className="text-muted">· {s.students}</span>
                      </span>
                    ))}
                  </div>
                )}
              </Panel>
            ))}
          </div>
        )}
      </div>
    </Layout>
  );
}
