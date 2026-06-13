import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { chatAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';
import {
  Send, Bot, User, BookOpen, Loader2, Trash2, Plus, X,
  Brain, AlertTriangle, Globe, Square, ChevronDown, Sparkles,
} from 'lucide-react';
import { v4 as uuidv4 } from 'uuid';

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

// ─── Extended-thinking (reasoning) trace ─────────────────────────────────────
function ThinkingTrace({ text, active }) {
  const [open, setOpen] = useState(false);
  // Auto-expand while Claude is actively thinking, auto-collapse once done.
  useEffect(() => { setOpen(active); }, [active]);
  if (!text && !active) return null;
  return (
    <div className="w-full max-w-full">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={`group relative flex items-center gap-2 text-xs font-semibold rounded-full pl-2.5 pr-3 py-1.5 transition-all duration-300 ${
          active
            ? 'text-white shadow-md shadow-indigo-300/50 bg-gradient-to-r from-indigo-500 via-violet-500 to-sky-500 bg-[length:200%_100%] animate-[shimmer_2.5s_linear_infinite]'
            : 'text-indigo-600 bg-indigo-50 ring-1 ring-inset ring-indigo-100 hover:bg-indigo-100'
        }`}
      >
        <Sparkles
          size={13}
          className={active ? 'text-white animate-[spin_3s_linear_infinite]' : 'text-indigo-500'}
        />
        <span className="tracking-tight">{active ? 'Thinking' : 'Thought process'}</span>
        <ChevronDown
          size={13}
          className={`transition-transform duration-300 ${open ? 'rotate-180' : ''} ${active ? 'text-white/80' : 'text-indigo-400'}`}
        />
      </button>
      <div className={`grid transition-all duration-300 ease-out ${open ? 'grid-rows-[1fr] opacity-100 mt-2' : 'grid-rows-[0fr] opacity-0'}`}>
        <div className="overflow-hidden">
          <div className="relative rounded-xl bg-gradient-to-br from-indigo-50/80 to-sky-50/60 ring-1 ring-inset ring-indigo-100/80 px-3.5 py-2.5">
            <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-full bg-gradient-to-b from-indigo-400 via-violet-400 to-sky-400" />
            <p className="text-[12.5px] leading-relaxed text-slate-500 whitespace-pre-wrap break-words pl-2">
              {text || (active ? 'Reasoning…' : '')}
              {active && <span className="inline-block w-1.5 h-3.5 ml-0.5 align-middle rounded-sm bg-indigo-400 animate-pulse" />}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}

// ─── Web search activity ──────────────────────────────────────────────────────
function WebSearchTrace({ searches }) {
  if (!searches?.length) return null;
  return (
    <div className="space-y-1">
      {searches.map((s, i) => (
        <div key={i} className="text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-100 rounded-lg px-2 py-1.5">
          <div className="flex items-center gap-1.5 font-medium">
            <Globe size={11} />
            <span>Searched the web for:</span>
            <span className="italic">"{s.query}"</span>
          </div>
          {s.urls?.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {s.urls.slice(0, 5).map((u, j) => (
                <a
                  key={j}
                  href={u.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-[10px] px-1.5 py-0.5 bg-white border border-emerald-200 rounded hover:bg-emerald-50 truncate max-w-[160px]"
                  title={u.title}
                >
                  {(() => { try { return new URL(u.url).hostname.replace('www.', ''); } catch { return u.url; } })()}
                </a>
              ))}
              {s.urls.length > 5 && (
                <span className="text-[10px] text-emerald-600">+{s.urls.length - 5} more</span>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─── Main component ──────────────────────────────────────────────────────────
export default function ChatInterface({ role = 'student' }) {
  useAuth();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [sessionId, setSessionId] = useState(uuidv4());
  const [subject, setSubject] = useState('');
  const [sessions, setSessions] = useState([]);
  const [showSessions, setShowSessions] = useState(true);
  const [memoryCount, setMemoryCount] = useState(0);
  const [showClearConfirm, setShowClearConfirm] = useState(false);
  const messagesEndRef = useRef(null);
  const inputRef = useRef(null);
  const abortRef = useRef(null);

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
      setShowClearConfirm(false);
      newChat();
    } catch (e) { console.error(e); }
  };

  return (
    <div className="flex h-full gap-4">
      {/* Sessions Panel */}
      {showSessions && (
        <div className="w-64 shrink-0 card flex flex-col gap-2">
          <div className="flex items-center justify-between mb-1">
            <span className="font-semibold text-sm text-gray-700">Chat History</span>
            <button onClick={() => setShowSessions(false)} className="text-gray-400 hover:text-gray-600">
              <X size={16} />
            </button>
          </div>

          {memoryCount > 0 && (
            <button
              onClick={() => setShowClearConfirm(true)}
              className="flex items-center gap-1.5 self-start text-[11px] text-gray-400 hover:text-red-500 transition-colors"
              title="Clear all chat history"
            >
              <Trash2 size={12} /> Clear history
            </button>
          )}

          {showClearConfirm && (
            <div className="p-2 bg-red-50 rounded-lg border border-red-200">
              <div className="flex items-center gap-1.5 mb-2">
                <AlertTriangle size={14} className="text-red-500" />
                <span className="text-xs text-red-700 font-medium">Delete all chat history?</span>
              </div>
              <p className="text-xs text-red-600 mb-2">This will permanently erase the AI's memory of your past conversations.</p>
              <div className="flex gap-1.5">
                <button onClick={clearAllMemory} className="flex-1 text-xs py-1 bg-red-500 text-white rounded hover:bg-red-600 transition-colors">Delete All</button>
                <button onClick={() => setShowClearConfirm(false)} className="flex-1 text-xs py-1 bg-white text-gray-600 rounded border border-gray-200 hover:bg-gray-50 transition-colors">Cancel</button>
              </div>
            </div>
          )}

          <button onClick={newChat} className="btn-primary text-sm flex items-center gap-2 justify-center py-1.5">
            <Plus size={14} /> New Chat
          </button>
          <div className="overflow-y-auto space-y-1 flex-1">
            {sessions.length === 0 && <p className="text-xs text-gray-400 text-center py-4">No chat history</p>}
            {sessions.map((s) => (
              <button
                key={s.session_id}
                onClick={() => loadSession(s.session_id)}
                className={`w-full text-left p-2 rounded-lg hover:bg-gray-50 group transition-colors ${
                  s.session_id === sessionId ? 'bg-blue-50 border border-blue-100' : ''
                }`}
              >
                <div className="flex items-start justify-between gap-1">
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-gray-700 truncate">{s.first_message || 'Chat session'}</p>
                    {s.subject && <span className="text-xs text-blue-600">{s.subject}</span>}
                    <p className="text-xs text-gray-400">
                      {(() => { const d = parseDate(s.last_message_at); return d ? d.toLocaleDateString() : ''; })()}
                    </p>
                  </div>
                  <button onClick={(e) => deleteSession(s.session_id, e)} className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 p-0.5">
                    <Trash2 size={12} />
                  </button>
                </div>
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Main Chat */}
      <div className="flex-1 flex flex-col card p-0 overflow-hidden min-w-0">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setShowSessions(!showSessions)}
              className="p-2 rounded-lg hover:bg-gray-100 text-gray-500 transition-colors"
              title="Chat history"
            >
              <BookOpen size={18} />
            </button>
            <div>
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-green-500" />
                <span className="font-semibold text-sm text-gray-800">AI Academic Assistant</span>
              </div>
              <p className="text-xs text-gray-500">
                Answers grounded in your school books, with web search when needed
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={subject}
              onChange={(e) => setSubject(e.target.value)}
              className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              <option value="">All Subjects</option>
              {SUBJECTS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
            <button onClick={newChat} className="p-2 rounded-lg hover:bg-gray-100 text-gray-500" title="New chat">
              <Plus size={18} />
            </button>
          </div>
        </div>

        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-center py-8">
              <div className="w-16 h-16 bg-blue-100 rounded-2xl flex items-center justify-center mb-4">
                <Bot size={32} className="text-blue-600" />
              </div>
              <h3 className="font-semibold text-gray-800 mb-1">AI Academic Assistant</h3>
              <p className="text-sm text-gray-500 max-w-xs">
                Ask anything from your subjects. Answers are grounded in your school's curriculum.
              </p>
              <div className="mt-4 grid grid-cols-2 gap-2 w-full max-w-xs">
                {['Explain photosynthesis', 'Summarize Chapter 3', 'What is algebra?', 'Create study notes'].map((q) => (
                  <button
                    key={q}
                    onClick={() => { setInput(q); inputRef.current?.focus(); }}
                    className="text-left text-xs p-2 rounded-lg bg-gray-50 hover:bg-blue-50 hover:text-blue-700 text-gray-600 border border-gray-100 transition-colors"
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg) => (
            <div key={msg.id} className={`flex gap-3 fade-in ${msg.role === 'user' ? 'flex-row-reverse' : ''}`}>
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5 ${
                msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'
              }`}>
                {msg.role === 'user' ? <User size={16} /> : <Bot size={16} />}
              </div>

              <div className={`max-w-[80%] flex flex-col gap-1.5 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
                {/* Extended-thinking trace (reasoning, collapsible) */}
                {msg.role === 'assistant' && (msg.thinking || (msg.streaming && !msg.content)) && (
                  <ThinkingTrace text={msg.thinking} active={!!msg.streaming} />
                )}

                {/* Web search trace (above text, like ChatGPT) */}
                {msg.role === 'assistant' && msg.web_searches?.length > 0 && (
                  <WebSearchTrace searches={msg.web_searches} />
                )}

                {/* Message body — hidden while only thinking is streaming */}
                {!(msg.role === 'assistant' && msg.streaming && !msg.content) && (
                <div className={`rounded-2xl px-4 py-3 text-sm ${
                  msg.role === 'user'
                    ? 'bg-blue-600 text-white rounded-tr-sm'
                    : 'bg-white border border-gray-100 shadow-sm text-gray-800 rounded-tl-sm'
                }`}>
                  {msg.role === 'user' ? (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  ) : (
                    <div className="prose-chat">
                      <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.content}</ReactMarkdown>
                      {msg.streaming && msg.content && (
                        <span className="inline-block w-1 h-4 bg-gray-400 animate-pulse ml-0.5" />
                      )}
                    </div>
                  )}
                </div>
                )}

              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>

        {/* Input */}
        <div className="p-4 border-t border-gray-100">
          <form onSubmit={sendMessage} className="flex gap-2">
            <input
              ref={inputRef}
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask a question about your studies..."
              disabled={streaming}
              className="flex-1 input-field disabled:bg-gray-50"
            />
            {streaming ? (
              <button
                type="button"
                onClick={stopStreaming}
                className="btn-primary px-3 py-2 bg-red-500 hover:bg-red-600 flex items-center gap-1"
                title="Stop generating"
              >
                <Square size={16} fill="white" />
              </button>
            ) : (
              <button
                type="submit"
                disabled={!input.trim()}
                className="btn-primary px-3 py-2"
              >
                <Send size={18} />
              </button>
            )}
          </form>
          <p className="text-xs text-gray-400 mt-1.5 text-center">
            Answers come from your school curriculum. Web search used only when needed.
          </p>
        </div>
      </div>
    </div>
  );
}
