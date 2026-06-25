import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';

// Renders GFM markdown (headings, bold, lists, tables, code) plus LaTeX math
// ($...$ / $$...$$) and chemistry (\ce{}) formulas via KaTeX, using the shared
// `prose-chat` styles. Reused anywhere we display AI-authored / markdown content.
export default function Markdown({ children, className = '' }) {
  return (
    <div className={`prose-chat ${className}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{children || ''}</ReactMarkdown>
    </div>
  );
}
