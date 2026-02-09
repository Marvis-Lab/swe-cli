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

      {/* Empty state — no session selected */}
      {!hasActiveSession && (
        <div className="absolute inset-0 flex items-center justify-center z-40 bg-beige-50/60">
          <p className="text-sm text-beige-400">
            Select a session or start a new conversation
          </p>
        </div>
      )}
    </div>
  );
}
