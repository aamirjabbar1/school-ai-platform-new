import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

// Renders GFM markdown (headings, bold, lists, tables, code) using the shared
// `prose-chat` styles. Reused anywhere we display AI-authored / markdown content.
export default function Markdown({ children, className = '' }) {
  return (
    <div className={`prose-chat ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{children || ''}</ReactMarkdown>
    </div>
  );
}
