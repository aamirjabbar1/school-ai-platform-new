import { useState, useRef, useEffect, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { chatAPI } from '../services/api';
import { useAuth } from '../context/AuthContext';
import { Send, Bot, User, BookOpen, Loader2, Trash2, Plus, X, Brain, AlertTriangle } from 'lucide-react';
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

export default function ChatInterface({ role = 'student' }) {
  const { user } = useAuth();
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
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
      setMessages(data.map((h) => ({
        id: h.id,
        role: h.role,
        content: h.content,
        sources: h.sources_used || [],
      })));
    } catch (e) {
      console.error(e);
    }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const { data } = await chatAPI.getSessions();
      setSessions(data);
      // Count total messages across all sessions for memory indicator
      const total = data.reduce((sum, s) => sum + (s.message_count || 0), 0);
      setMemoryCount(total);
    } catch (e) {
      console.error(e);
    }
  }, []);

  useEffect(() => { loadSessions(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const sendMessage = async (e) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text || loading || streaming) return;

    const userMsg = { id: Date.now(), role: 'user', content: text, sources: [] };
    setMessages((prev) => [...prev, userMsg]);
    setInput('');
    setStreaming(true);
    setLoading(true);

    // Placeholder for streaming assistant message
    const assistantMsgId = Date.now() + 1;
    setMessages((prev) => [...prev, {
      id: assistantMsgId, role: 'assistant', content: '', sources: [], streaming: true
    }]);

    try {
      const response = await chatAPI.sendMessage({
        message: text,
        subject: subject || undefined,
        session_id: sessionId,
      });

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let fullContent = '';
      let finalSources = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split('\n');

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6));
              if (data.type === 'chunk') {
                fullContent += data.content;
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: fullContent }
                      : m
                  )
                );
              } else if (data.type === 'done') {
                finalSources = data.sources || [];
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: fullContent, sources: finalSources, streaming: false }
                      : m
                  )
                );
              } else if (data.type === 'error') {
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === assistantMsgId
                      ? { ...m, content: 'Sorry, an error occurred. Please try again.', streaming: false }
                      : m
                  )
                );
              }
            } catch {}
          }
        }
      }
    } catch (err) {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsgId
            ? { ...m, content: 'Connection error. Please try again.', streaming: false }
            : m
        )
      );
    } finally {
      setStreaming(false);
      setLoading(false);
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
    } catch (e) {
      console.error(e);
    }
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

          {/* Memory indicator */}
          {memoryCount > 0 && (
            <div className="flex items-center gap-2 px-2 py-1.5 bg-purple-50 rounded-lg border border-purple-100">
              <Brain size={14} className="text-purple-600 shrink-0" />
              <span className="text-xs text-purple-700 flex-1">
                {memoryCount} messages remembered
              </span>
              <button
                onClick={() => setShowClearConfirm(true)}
                className="text-purple-400 hover:text-red-500 transition-colors"
                title="Clear all memory"
              >
                <Trash2 size={12} />
              </button>
            </div>
          )}

          {/* Clear memory confirmation */}
          {showClearConfirm && (
            <div className="p-2 bg-red-50 rounded-lg border border-red-200">
              <div className="flex items-center gap-1.5 mb-2">
                <AlertTriangle size={14} className="text-red-500" />
                <span className="text-xs text-red-700 font-medium">Delete all chat history?</span>
              </div>
              <p className="text-xs text-red-600 mb-2">This will permanently erase the AI's memory of your past conversations.</p>
              <div className="flex gap-1.5">
                <button
                  onClick={clearAllMemory}
                  className="flex-1 text-xs py-1 bg-red-500 text-white rounded hover:bg-red-600 transition-colors"
                >
                  Delete All
                </button>
                <button
                  onClick={() => setShowClearConfirm(false)}
                  className="flex-1 text-xs py-1 bg-white text-gray-600 rounded border border-gray-200 hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          <button onClick={newChat} className="btn-primary text-sm flex items-center gap-2 justify-center py-1.5">
            <Plus size={14} /> New Chat
          </button>
          <div className="overflow-y-auto space-y-1 flex-1">
            {sessions.length === 0 && (
              <p className="text-xs text-gray-400 text-center py-4">No chat history</p>
            )}
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
                    <p className="text-xs font-medium text-gray-700 truncate">
                      {s.first_message || 'Chat session'}
                    </p>
                    {s.subject && (
                      <span className="text-xs text-blue-600">{s.subject}</span>
                    )}
                    <p className="text-xs text-gray-400">
                      {(() => { const d = parseDate(s.last_message_at); return d ? d.toLocaleDateString() : ''; })()}
                    </p>
                  </div>
                  <button
                    onClick={(e) => deleteSession(s.session_id, e)}
                    className="opacity-0 group-hover:opacity-100 text-gray-400 hover:text-red-500 p-0.5"
                  >
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
        {/* Chat Header */}
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
                {memoryCount > 0 && (
                  <span className="flex items-center gap-1 text-xs text-purple-600 bg-purple-50 px-1.5 py-0.5 rounded-full">
                    <Brain size={10} /> Memory Active
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-500">
                {memoryCount > 0
                  ? 'Remembers your past conversations for personalized help'
                  : 'Answers based strictly on school curriculum content'
                }
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
            <button
              onClick={newChat}
              className="p-2 rounded-lg hover:bg-gray-100 text-gray-500"
              title="New chat"
            >
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
                Ask questions about your subjects. I answer strictly from the school's curriculum and uploaded books.
              </p>
              {memoryCount > 0 && (
                <p className="text-xs text-purple-600 mt-2 flex items-center gap-1">
                  <Brain size={12} /> I remember your previous conversations and will build on them
                </p>
              )}
              <div className="mt-4 grid grid-cols-2 gap-2 w-full max-w-xs">
                {[
                  'Explain photosynthesis',
                  'Summarize Chapter 3',
                  'What is algebra?',
                  'Create study notes',
                ].map((q) => (
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
              <div className={`w-8 h-8 rounded-full flex items-center justify-center shrink-0 mt-0.5
                ${msg.role === 'user' ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600'}`}>
                {msg.role === 'user' ? <User size={16} /> : <Bot size={16} />}
              </div>
              <div className={`max-w-[80%] ${msg.role === 'user' ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
                <div className={`rounded-2xl px-4 py-3 text-sm
                  ${msg.role === 'user'
                    ? 'bg-blue-600 text-white rounded-tr-sm'
                    : 'bg-white border border-gray-100 shadow-sm text-gray-800 rounded-tl-sm'
                  }`}
                >
                  {msg.role === 'user' ? (
                    <p className="whitespace-pre-wrap">{msg.content}</p>
                  ) : (
                    <div className="prose-chat">
                      {msg.streaming && !msg.content ? (
                        <div className="flex gap-1.5 py-1">
                          <div className="typing-dot" />
                          <div className="typing-dot" />
                          <div className="typing-dot" />
                        </div>
                      ) : (
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {msg.content}
                        </ReactMarkdown>
                      )}
                      {msg.streaming && msg.content && (
                        <span className="inline-block w-1 h-4 bg-gray-400 animate-pulse ml-0.5" />
                      )}
                    </div>
                  )}
                </div>
                {/* Sources */}
                {msg.sources?.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {msg.sources.slice(0, 3).map((s, i) => (
                      <span key={i} className="text-xs px-2 py-0.5 bg-blue-50 text-blue-600 rounded-full border border-blue-100">
                        {s.title}
                      </span>
                    ))}
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
            <button
              type="submit"
              disabled={!input.trim() || streaming}
              className="btn-primary px-3 py-2"
            >
              {streaming ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
            </button>
          </form>
          <p className="text-xs text-gray-400 mt-1.5 text-center">
            AI responses are limited to school curriculum materials only
          </p>
        </div>
      </div>
    </div>
  );
}
