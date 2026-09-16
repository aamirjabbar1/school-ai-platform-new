import { useEffect, useState } from 'react';
import Layout from '../../components/Layout';
import { API_ORIGIN, onlineClassAPI } from '../../services/api';
import { apiError } from '../../services/apiError';
import { Play, Video, X, CalendarDays } from 'lucide-react';

// RECORDED CLASSES (spec §15). A student sees only the recordings of their own
// class and section, and each playback link is a short-lived token rather than
// a shareable URL — these are recordings of children, not public content.
export default function RecordedClasses() {
  const [recordings, setRecordings] = useState([]);
  const [loading, setLoading] = useState(true);
  const [playing, setPlaying] = useState(null);
  const [streamUrl, setStreamUrl] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    onlineClassAPI.recordings()
      .then(({ data }) => setRecordings(data.recordings || []))
      .catch(() => setError('Could not load your recorded classes.'))
      .finally(() => setLoading(false));
  }, []);

  const play = async (recording) => {
    setError('');
    try {
      const { data } = await onlineClassAPI.recordingToken(recording.id);
      setStreamUrl(`${API_ORIGIN}${data.url}?rt=${encodeURIComponent(data.token)}`);
      setPlaying(recording);
    } catch (err) {
      setError(apiError(err, 'This recording cannot be played right now.'));
    }
  };

  const close = () => {
    setPlaying(null);
    setStreamUrl('');
  };

  return (
    <Layout title="Recorded Classes">
      {error && <div className="card mb-4 text-sm text-rose-400">{error}</div>}

      {loading && <div className="card text-muted text-sm">Loading…</div>}

      {!loading && recordings.length === 0 && (
        <div className="card text-center py-10">
          <Video size={36} className="mx-auto text-faint mb-3" />
          <div className="font-display font-semibold text-ink">No recordings yet</div>
          <p className="text-sm text-muted mt-1">
            When your teacher records a class, it appears here.
          </p>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {recordings.map((recording) => (
          <button
            key={recording.id}
            onClick={() => play(recording)}
            className="card text-left hover:shadow-glow transition-shadow group"
          >
            <div className="flex items-center gap-3">
              <div className="w-11 h-11 rounded-2xl bg-gradient-to-br from-brand-blue to-brand-violet
                              flex items-center justify-center text-white shadow-glow
                              group-hover:scale-105 transition-transform">
                <Play size={20} />
              </div>
              <div className="min-w-0">
                <div className="font-semibold text-ink truncate">{recording.subject}</div>
                <div className="text-sm text-muted flex items-center gap-1.5">
                  <CalendarDays size={13} />
                  {recording.class_date
                    ? new Date(recording.class_date).toLocaleDateString([], { day: 'numeric', month: 'long' })
                    : '—'}
                </div>
              </div>
            </div>
            <div className="text-xs text-muted mt-3">
              {recording.teacher_name}
              {recording.duration_seconds
                ? ` · ${Math.round(recording.duration_seconds / 60)} min`
                : ''}
            </div>
          </button>
        ))}
      </div>

      {playing && (
        <div className="fixed inset-0 z-50 bg-slate-950/80 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-4xl">
            <div className="flex items-center justify-between mb-2 text-white">
              <div className="font-semibold">
                {playing.subject} —{' '}
                {playing.class_date && new Date(playing.class_date).toLocaleDateString()}
              </div>
              <button onClick={close} className="p-2 rounded-xl hover:bg-white/10">
                <X size={20} />
              </button>
            </div>
            {/* controlsList/disablePictureInPicture keep the file one step
                further from being casually saved and passed around. */}
            <video
              src={streamUrl}
              controls
              autoPlay
              controlsList="nodownload"
              disablePictureInPicture
              className="w-full rounded-2xl bg-black max-h-[75vh]"
            />
          </div>
        </div>
      )}
    </Layout>
  );
}
