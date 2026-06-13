import { useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { chatAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { History, Plus, User } from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';

import AiOrb from './chat/AiOrb';
import ThinkingTrace from './chat/ThinkingTrace';
import WebSearchTrace from './chat/WebSearchTrace';
import SourcesCard from './chat/SourcesCard';
import WelcomeHero from './chat/WelcomeHero';
import Composer from './chat/Composer';
import SessionsDrawer from './chat/SessionsDrawer';
import StatsBar from './chat/StatsBar';

const SUBJECTS = [
  'Mathematics', 'Science', 'English', 'Urdu', 'Islamiat',
  'Computer Science', 'Social Studies', 'Physics', 'Chemistry', 'Biology', 'History', 'Geography',
];

function parseDate(raw) {
  if (!raw) return null;
  const d = new Date(String(raw).replace(/(\d{2}:\d{2}:\d{2}(?:\.\d+)?)\s+([+-])/, '$1$2'));
  return isNaN(d) ? null : d;
}

// Normalize sources_used from history rows. Backend stores it as
// {kb_sources, web_searches}; legacy rows may store a plain array of sources.
function normalizeSources(raw) {
  if (!raw) return { kb_sources: [], web_searches: [] };
  if (Array.isArray(raw)) {
    return { kb_sources: raw, web_searches: [] };
  }
  return {
    kb_sources:    raw.kb_sources    || [],
    web_searches:  raw.web_searches  || [],
  };
}

// Honest gamification: derive a day-streak / questions / chats count from the
// existing session list — no backend changes.
function computeStats(sessions) {
  const questions = sessions.reduce((sum, s) => sum + Math.max(1, Math.ceil((s.message_count || 0) / 2)), 0);
  const topics = sessions.length;
  const days = new Set();
  sessions.forEach((s) => {
    const d = parseDate(s.last_message_at) || parseDate(s.started_at);
    if (d) days.add(d.toDateString());
  });
  let streak = 0;
  const cur = new Date();
  if (!days.has(cur.toDateString())) {
    cur.setDate(cur.getDate() - 1);
    if (!days.has(cur.toDateString())) return { questions, topics, streak: 0 };
  }
  while (days.has(cur.toDateString())) {
    streak += 1;
    cur.setDate(cur.getDate() - 1);
  }
  return { questions, topics, streak };
}

// ─── Main component ──────────────────────────────────────────────────────────
export default function ChatInterface({ role = 'student' }) {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState(uuidv4());
  const [subject, setSubject] = useState('');
  const [sessions, setSessions] = useState([]);
  const [showSessions, setShowSessions] = useState(false);
  const [memoryCount, setMemoryCount] = useState(0);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

  const stats = useMemo(() => computeStats(sessions), [sessions]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => { scrollToBottom(); }, [messages]);

  const loadHistory = useCallback(async (sid) => {
    try {
      const { data } = await chatAPI.getHistory({ session_id: sid });
      setMessages(data.map((h) => {
        const src = normalizeSources(h.sources_used);
        return {
          id: h.id,
          role: h.role,
          content: h.content,
          kb_sources:    src.kb_sources,
          web_searches:  src.web_searches,
        };
      }));
    } catch (e) { console.error(e); }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const { data } = await chatAPI.getSessions();
      setSessions(data);
      const total = data.reduce((sum, s) => sum + (s.message_count || 0), 0);
      setMemoryCount(total);
    } catch (e) { console.error(e); }
  }, []);

  useEffect(() => { loadSessions(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const stopStreaming = () => {
    abortRef.current?.abort();
  };

  const sendMessage = async (e) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || streaming) return;

    const userMsg = { id: Date.now(), role: 'user', content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setStreaming(true);

    const assistantMsgId = Date.now() + 1;
    setMessages((prev) => [...prev, {
      id: assistantMsgId,
      role: 'assistant',
      content: '',
      thinking: '',
      segments: {},
      intermediateSegs: [],
      web_searches: [],
      kb_sources: [],
      streaming: true,
    }]);

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const response = await chatAPI.sendMessage(
        { message: text, subject: subject || undefined, session_id: sessionId },
        controller.signal,
      );

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      // ── SSE event-by-event parser ──────────────────────────────────────
      // Events are separated by a blank line ("\n\n"). A single network read
      // may contain partial events; keep them in `buffer` until terminated.
      const handleEvent = (eventText) => {
        for (const line of eventText.split('\n')) {
          if (!line.startsWith('data: ')) continue;
          const payload = line.slice(6);
          if (!payload) continue;
          let data;
          try { data = JSON.parse(payload); } catch { continue; }
          dispatchEvent(data);
        }
      };

      const dispatchEvent = (data) => {
        switch (data.type) {
          case 'start':
            // session confirmation; nothing to render
            break;

          case 'text': {
            // data = { text, seg }. Accumulate per segment; the answer is the
            // concatenation of segments that did NOT call tools.
            const { text: chunk = '', seg = 0 } = data;
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantMsgId) return m;
              const segments = { ...(m.segments || {}) };
              segments[seg] = (segments[seg] || '') + chunk;
              const interm = m.intermediateSegs || [];
              const content = Object.keys(segments)
                .map(Number).sort((a, b) => a - b)
                .filter((s) => !interm.includes(s))
                .map((s) => segments[s]).join('');
              return { ...m, segments, content };
            }));
            break;
          }

          case 'intermediate': {
            // This segment was a tool-calling step — its text is reasoning, not
            // the answer. Move it into the thinking panel and drop from content.
            const seg = data.seg ?? 0;
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantMsgId) return m;
              const interm = m.intermediateSegs?.includes(seg)
                ? m.intermediateSegs
                : [...(m.intermediateSegs || []), seg];
              const segments = m.segments || {};
              const narration = (segments[seg] || '').trim();
              const thinking = narration
                ? `${m.thinking ? m.thinking.replace(/\s*$/, '') + '\n' : ''}${narration}`
                : (m.thinking || '');
              const content = Object.keys(segments)
                .map(Number).sort((a, b) => a - b)
                .filter((s) => !interm.includes(s))
                .map((s) => segments[s]).join('');
              return { ...m, intermediateSegs: interm, thinking, content };
            }));
            break;
          }

          case 'thinking':
            setMessages((prev) => prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, thinking: (m.thinking || '') + data.text }
                : m
            ));
            break;

          case 'web_search_query':
            setMessages((prev) => prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    web_searches: [
                      ...(m.web_searches || []),
                      { query: data.query, urls: [], pending: true },
                    ],
                  }
                : m
            ));
            break;

          case 'web_search_result':
            setMessages((prev) => prev.map((m) => {
              if (m.id !== assistantMsgId) return m;
              const ws = [...(m.web_searches || [])];
              // Attach to most recent pending search
              for (let i = ws.length - 1; i >= 0; i--) {
                if (ws[i].pending) {
                  ws[i] = { ...ws[i], urls: data.results, pending: false };
                  break;
                }
              }
              return { ...m, web_searches: ws };
            }));
            break;

          case 'tool_use':
            // generic tool indicator (non-search tools, future)
            break;

          case 'done':
            setMessages((prev) => prev.map((m) =>
              m.id === assistantMsgId
                ? {
                    ...m,
                    content:       data.message || m.content,
                    web_searches:  data.web_searches || m.web_searches,
                    kb_sources:    data.sources      || [],
                    streaming:     false,
                  }
                : m
            ));
            break;

          case 'error':
            setMessages((prev) => prev.map((m) =>
              m.id === assistantMsgId
                ? { ...m, content: `Error: ${data.message}`, streaming: false }
                : m
            ));
            break;

          default:
            // forward-compatibility: ignore unknown event types
            break;
        }
      };

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // Split out fully-terminated events. Anything after the last "\n\n"
        // is a partial event still being received — keep it in buffer.
        let sepIdx;
        while ((sepIdx = buffer.indexOf('\n\n')) !== -1) {
          const eventText = buffer.slice(0, sepIdx);
          buffer = buffer.slice(sepIdx + 2);
          if (eventText.trim()) handleEvent(eventText);
        }
      }

      // Drain any remaining content (partial event without trailing blank line)
      if (buffer.trim()) handleEvent(buffer);

    } catch (err) {
      if (err.name === 'AbortError') {
        setMessages((prev) => prev.map((m) =>
          m.id === assistantMsgId ? { ...m, streaming: false } : m
        ));
      } else {
        setMessages((prev) => prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, content: m.content || 'Connection error. Please try again.', streaming: false }
            : m
        ));
      }
    } finally {
      setStreaming(false);
      abortRef.current = null;
      loadSessions();
    }
  };

  const newChat = () => {
    setMessages([]);
    setSessionId(uuidv4());
    setShowSessions(false);
    inputRef.current?.focus();
  };

  const loadSession = async (sid) => {
    setSessionId(sid);
    await loadHistory(sid);
    setShowSessions(false);
  };

  const deleteSession = async (sid, e) => {
    e.stopPropagation();
    try {
      await chatAPI.deleteSession(sid);
      setSessions((prev) => prev.filter((s) => s.session_id !== sid));
      if (sid === sessionId) newChat();
    } catch {}
  };

  const clearAllMemory = async () => {
    try {
      await chatAPI.clearMemory();
      setSessions([]);
      setMemoryCount(0);
      newChat();
    } catch (e) { console.error(e); }
  };

  const pickPrompt = (q) => {
    setInput(q);
    inputRef.current?.focus();
  };

  return (
    <div className="relative flex flex-col h-full min-h-0 rounded-3xl overflow-hidden glass">
      {/* Header */}
      <header className="flex items-center justify-between gap-2 px-3 sm:px-4 py-2.5 border-b border-line/60 glass-strong">
        <div className="flex items-center gap-2.5 min-w-0">
          <button
            onClick={() => setShowSessions(true)}
            className="h-9 w-9 inline-flex items-center justify-center rounded-xl glass text-muted hover:text-ink transition-colors"
            title="Chat history"
            aria-label="Open chat history"
          >
            <History size={17} />
          </button>
          <AiOrb size={30} icon active={streaming} />
          <div className="min-w-0">
            <div className="flex items-center gap-1.5">
              <span className="font-display font-bold text-sm text-ink truncate">LSS AI Tutor</span>
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-70 animate-ping" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
            </div>
            <p className="text-[11px] text-muted truncate hidden sm:block">Curriculum-grounded · always here to help</p>
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          <StatsBar streak={stats.streak} questions={stats.questions} topics={stats.topics} />
          <button
            onClick={newChat}
            className="h-9 w-9 inline-flex items-center justify-center rounded-xl glass text-muted hover:text-ink transition-colors"
            title="New chat"
            aria-label="New chat"
          >
            <Plus size={18} />
          </button>
        </div>
      </header>

      {/* Conversation */}
      {messages.length === 0 ? (
        <div className="flex-1 overflow-y-auto">
          <WelcomeHero userName={user?.name} role={role} onPick={pickPrompt} />
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-3 sm:px-4 py-6 space-y-6">
            <AnimatePresence initial={false}>
              {messages.map((msg) => {
                const isUser = msg.role === 'user';
                const onlyThinking = msg.role === 'assistant' && msg.streaming && !msg.content;
                return (
                  <motion.div
                    key={msg.id}
                    initial={{ opacity: 0, y: 14 }}
                    animate={{ opacity: 1, y: 0 }}
                    transition={{ duration: 0.3, ease: 'easeOut' }}
                    className={`flex gap-3 ${isUser ? 'flex-row-reverse' : ''}`}
                  >
                    {/* Avatar */}
                    {isUser ? (
                      <div className="w-8 h-8 rounded-full bg-gradient-to-br from-brand-blue to-brand-violet flex items-center justify-center shrink-0 mt-0.5 text-white shadow-glow">
                        <User size={15} />
                      </div>
                    ) : (
                      <AiOrb size={32} icon active={!!msg.streaming} className="mt-0.5" />
                    )}

                    {/* Content */}
                    <div className={`max-w-[85%] flex flex-col gap-2 ${isUser ? 'items-end' : 'items-start'}`}>
                      {msg.role === 'assistant' && (msg.thinking || onlyThinking) && (
                        <ThinkingTrace text={msg.thinking} active={!!msg.streaming} />
                      )}

                      {msg.role === 'assistant' && msg.web_searches?.length > 0 && (
                        <WebSearchTrace searches={msg.web_searches} />
                      )}

                      {!onlyThinking && (
                        <div className={`px-4 py-3 text-sm shadow-soft ${
                          isUser
                            ? 'bg-gradient-to-br from-brand-blue to-brand-violet text-white rounded-2xl rounded-tr-md'
                            : 'glass-strong text-ink rounded-2xl rounded-tl-md'
                        }`}>
                          {isUser ? (
                            <p className="whitespace-pre-wrap">{msg.content}</p>
                          ) : (
                            <div className="prose-chat">
                              <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                              {msg.streaming && msg.content && (
                                <span className="inline-block w-1.5 h-4 rounded-sm bg-brand-cyan animate-pulse ml-0.5 align-middle" />
                              )}
                            </div>
                          )}
                        </div>
                      )}

                      {/* NEW: book sources grounding the answer */}
                      {msg.role === 'assistant' && msg.kb_sources?.length > 0 && (
                        <SourcesCard sources={msg.kb_sources} />
                      )}
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
            <div ref={messagesEndRef} />
          </div>
        </div>
      )}

      {/* Composer */}
      <Composer
        input={input}
        setInput={setInput}
        onSubmit={sendMessage}
        streaming={streaming}
        onStop={stopStreaming}
        subject={subject}
        setSubject={setSubject}
        subjects={SUBJECTS}
        inputRef={inputRef}
      />

      {/* Sessions drawer */}
      <SessionsDrawer
        open={showSessions}
        onClose={() => setShowSessions(false)}
        sessions={sessions}
        activeId={sessionId}
        memoryCount={memoryCount}
        onLoad={loadSession}
        onDelete={deleteSession}
        onNew={newChat}
        onClearAll={clearAllMemory}
      />
    </div>
  );
}
