import { useEffect } from 'react';
import { useChatStore } from '../../stores/chat';
import { MessageList } from './MessageList';
import { InputBox } from './InputBox';
import { StatusBar } from '../StatusBar';

export function ChatInterface() {
  const error = useChatStore(state => state.error);
  const currentSessionId = useChatStore(state => state.currentSessionId);
  const hasActiveSession = !!currentSessionId;

  useEffect(() => {
    // No auto-initialization - user selects session from sidebar
  }, []);

  return (
    <div className="flex flex-col h-full relative">
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-800 px-4 py-3 mx-6 mt-4 rounded-lg">
          <strong className="font-semibold">Error:</strong> {error}
        </div>
      )}

      <MessageList />
      <InputBox />
      <StatusBar />

      {/* Session Required Overlay */}
      {!hasActiveSession && (
        <div className="absolute inset-0 flex items-center justify-center z-40 bg-gradient-to-b from-white to-beige-50/80">
          <div className="text-center max-w-sm px-6">
            {/* Logo mark */}
            <div className="w-14 h-14 mx-auto mb-5 rounded-xl bg-gradient-to-br from-amber-400 via-orange-500 to-rose-500 flex items-center justify-center shadow-lg">
              <svg className="w-7 h-7 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4" />
              </svg>
            </div>

            <h2 className="text-xl font-semibold text-gray-900 mb-2">
              OpenDev
            </h2>
            <p className="text-sm text-beige-500 leading-relaxed">
              Select a session from the sidebar or start a new conversation to begin.
            </p>

            {/* Keyboard shortcut hint */}
            <div className="mt-6 inline-flex items-center gap-2 text-xs text-beige-400">
              <kbd className="px-1.5 py-0.5 rounded border border-beige-200 bg-white text-beige-500 font-mono text-[10px]">Ctrl</kbd>
              <span>+</span>
              <kbd className="px-1.5 py-0.5 rounded border border-beige-200 bg-white text-beige-500 font-mono text-[10px]">B</kbd>
              <span className="ml-1">toggle sidebar</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
