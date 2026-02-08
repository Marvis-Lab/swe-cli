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
        <div className="absolute inset-0 bg-white/95 backdrop-blur-sm flex items-center justify-center z-40">
          <div className="text-center max-w-md px-6">
            <div className="w-20 h-20 mx-auto mb-6 rounded-2xl bg-gradient-to-br from-blue-500 to-purple-600 flex items-center justify-center shadow-xl">
              <svg className="w-10 h-10 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z" />
              </svg>
            </div>
            <h2 className="text-2xl font-bold text-gray-900 mb-3">
              No Session Selected
            </h2>
            <p className="text-gray-600 mb-6 leading-relaxed">
              To start chatting, please select an existing session from the sidebar or start a new conversation.
            </p>
            <div className="flex items-center justify-center gap-2 text-sm text-gray-500">
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>Click a session or "Start Conversation" to get started</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
