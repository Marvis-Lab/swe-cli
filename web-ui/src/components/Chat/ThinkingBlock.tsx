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
      <div className="bg-gray-100 border border-gray-200 rounded-lg overflow-hidden">
        {/* Header - always visible */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full px-4 py-2 flex items-center gap-2 text-left hover:bg-gray-200 transition-colors cursor-pointer"
        >
          <svg
            className={`w-3.5 h-3.5 text-gray-400 transition-transform duration-200 flex-shrink-0 ${
              isExpanded ? 'rotate-90' : ''
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
          <span className="text-xs font-medium text-gray-500 uppercase tracking-wide">Thinking</span>
          <span className="text-xs text-gray-400">({charCount.toLocaleString()} chars)</span>
          {!isExpanded && (
            <span className="text-xs text-gray-400 truncate ml-2 italic">
              {preview}...
            </span>
          )}
        </button>

        {/* Content - collapsible */}
        {isExpanded && (
          <div className="px-4 pb-3 border-t border-gray-200">
            <pre className="text-xs text-gray-600 whitespace-pre-wrap font-mono leading-relaxed mt-2 max-h-96 overflow-y-auto">
              {content}
            </pre>
          </div>
        )}
      </div>
    </div>
  );
}
