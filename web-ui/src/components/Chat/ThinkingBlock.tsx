import { useState } from 'react';

interface ThinkingBlockProps {
  content: string;
}

export function ThinkingBlock({ content }: ThinkingBlockProps) {
  const [isExpanded, setIsExpanded] = useState(false);

  const charCount = content.length;
  const preview = content.substring(0, 120).replace(/\n/g, ' ');

  return (
    <div className="animate-slide-up">
      <div className="bg-bg-100 border border-border-300/15 rounded-lg overflow-hidden">
        {/* Header - always visible */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full px-4 py-2 flex items-center gap-2 text-left hover:bg-bg-200 transition-colors cursor-pointer"
        >
          <svg
            className={`w-3.5 h-3.5 text-text-500 transition-transform duration-200 flex-shrink-0 ${
              isExpanded ? 'rotate-90' : ''
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="text-xs font-medium text-text-400 uppercase tracking-wide">Thinking</span>
          <span className="text-xs text-text-500">({charCount.toLocaleString()} chars)</span>
          {!isExpanded && (
            <span className="text-xs text-text-500 truncate ml-2 italic">
              {preview}...
            </span>
          )}
        </button>

        {/* Content - collapsible */}
        {isExpanded && (
          <div className="px-4 pb-3 border-t border-border-300/15">
            <pre className="text-xs text-text-300 whitespace-pre-wrap font-mono leading-relaxed mt-2 max-h-96 overflow-y-auto">
              {content}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
