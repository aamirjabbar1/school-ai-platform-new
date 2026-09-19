/**
 * Families.
 *
 * The specification asks for one thing here above all: open a family, see every
 * child in it. That is the whole screen. Sibling discounts, fee concessions and
 * "who else do we teach from this house" all start from this view, so it stays
 * a list and a panel rather than a form.
 */
import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { erpAPI } from '../../services/api';
import { Busy, Drawer, Empty, Note, Panel } from '../../components/erp/Kit';
import { Home, Phone, Search, Users } from 'lucide-react';

export default function ErpFamilies() {
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [data, setData] = useState({ families: [], total: 0 });
  const [open, setOpen] = useState(null);
  const [detail, setDetail] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const { data } = await erpAPI.families({ q: query || undefined });
        setData(data);
      } catch (e) {
        setError(e.response?.data?.detail || 'Could not load families.');
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => clearTimeout(timer);
  }, [query]);

  const openFamily = async (family) => {
    setOpen(family);
    setDetail(null);
    try {
      const { data } = await erpAPI.family(family.id);
      setDetail(data);
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not open that family.');
    }
  };

  return (
    <Layout title="Families">
      <div className="space-y-4 max-w-5xl">
        {error && <Note kind="bad">{error}</Note>}

        <Panel>
          <div className="relative">
            <Search size={18} className="absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by father’s name, phone or family code…"
              className="w-full min-h-[48px] rounded-xl pl-10 pr-3 bg-surface-2 border border-line text-ink
                         focus:outline-none focus:ring-2 focus:ring-brand-cyan/60"
            />
          </div>
        </Panel>

        {loading ? (
          <Busy label="Loading families…" />
        ) : data.families.length === 0 ? (
          <Empty
            icon={Home}
            title="No families yet"
            hint="Families are created as students are admitted, and siblings are linked to them automatically."
          />
        ) : (
          <>
            <p className="text-sm text-muted px-1">{data.total} families</p>
            <div className="space-y-2">
              {data.families.map((f) => (
                <button
                  key={f.id}
                  onClick={() => openFamily(f)}
                  className="card w-full text-left hover:scale-[1.005] transition-transform flex items-center gap-4 min-h-[72px]"
                >
                  <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-brand-purple via-brand-violet to-brand-blue
                                  flex items-center justify-center text-white shrink-0">
                    <Home size={20} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="font-semibold text-ink truncate">{f.father_name || f.family_code}</div>
                    <div className="text-sm text-muted truncate">
                      {f.phone ? `${f.phone} · ` : ''}{f.family_code}
                    </div>
                  </div>
                  <div className="flex items-center gap-2 text-ink shrink-0">
                    <Users size={16} className="text-brand-cyan" />
                    <span className="font-bold">{f.children}</span>
                  </div>
                </button>
              ))}
            </div>
          </>
        )}
      </div>

      <Drawer
        open={!!open}
        title={open?.father_name || open?.family_code}
        subtitle={open?.family_code}
        onClose={() => setOpen(null)}
      >
        {!detail ? (
          <Busy label="Opening…" />
        ) : (
          <>
            <div className="rounded-2xl bg-surface-2/60 p-4 space-y-2 text-sm">
              {detail.phone && (
                <div className="flex items-center gap-2 text-ink">
                  <Phone size={15} className="text-brand-cyan" /> {detail.phone}
                </div>
              )}
              {detail.address && <p className="text-muted">{detail.address}</p>}
              {detail.cnic && <p className="text-muted">CNIC {detail.cnic}</p>}
            </div>

            {detail.guardians?.length > 0 && (
              <div>
                <h4 className="text-sm font-semibold text-ink mb-2">Parents and guardians</h4>
                <div className="space-y-2">
                  {detail.guardians.map((g) => (
                    <div key={g.id} className="rounded-xl bg-surface-2/60 p-3">
                      <div className="font-medium text-ink">{g.name}</div>
                      <div className="text-sm text-muted">
                        {[g.relation, g.phone].filter(Boolean).join(' · ')}
                        {g.is_primary ? ' · main contact' : ''}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <h4 className="text-sm font-semibold text-ink mb-2">
                {detail.children.length} {detail.children.length === 1 ? 'child' : 'children'} in the school
              </h4>
              {detail.children.length === 0 ? (
                <p className="text-sm text-muted">No children linked to this family yet.</p>
              ) : (
                <div className="space-y-2">
                  {detail.children.map((c) => (
                    <div key={c.id} className="rounded-xl bg-surface-2/60 p-3 flex items-center gap-3">
                      <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-brand-blue to-brand-cyan
                                      flex items-center justify-center text-white text-sm font-bold shrink-0">
                        {c.name?.charAt(0)?.toUpperCase()}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="font-medium text-ink truncate">{c.name}</div>
                        <div className="text-sm text-muted truncate">
                          {c.class_name || 'No class'}{c.section_name ? ` ${c.section_name}` : ''}
                        </div>
                      </div>
                      <div className="text-right shrink-0">
                        <div className="text-xs text-faint">GR</div>
                        <div className="font-mono text-sm text-ink">{c.gr_no || '—'}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </>
        )}
      </Drawer>
    </Layout>
  );
}
