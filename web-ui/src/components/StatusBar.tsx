import { useEffect } from 'react';
import { useChatStore } from '../stores/chat';
import { apiClient } from '../api/client';

const MODE_STYLES = {
  normal: 'bg-blue-100 text-blue-700 hover:bg-blue-200',
  plan: 'bg-purple-100 text-purple-700 hover:bg-purple-200',
} as const;

const AUTONOMY_STYLES = {
  'Manual': 'bg-orange-100 text-orange-700 hover:bg-orange-200',
  'Semi-Auto': 'bg-cyan-100 text-cyan-700 hover:bg-cyan-200',
  'Auto': 'bg-green-100 text-green-700 hover:bg-green-200',
} as const;

export function StatusBar() {
  const status = useChatStore(state => state.status);
  const showThinking = useChatStore(state => state.showThinking);
  const toggleMode = useChatStore(state => state.toggleMode);
  const cycleAutonomy = useChatStore(state => state.cycleAutonomy);
  const toggleThinking = useChatStore(state => state.toggleThinking);

  // Load initial status on mount
  useEffect(() => {
    const loadStatus = async () => {
      try {
        const configData = await apiClient.getConfig();
        useChatStore.getState().setStatus({
          mode: configData.mode || 'normal',
          autonomy_level: configData.autonomy_level || 'Manual',
          model: configData.model,
          model_provider: configData.model_provider,
          working_dir: configData.working_dir || '',
          git_branch: configData.git_branch,
        });
      } catch (_) { /* ignore */ }
    };
    loadStatus();
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === 'T') {
        e.preventDefault();
        toggleThinking();
      }
      if (e.ctrlKey && e.shiftKey && e.key === 'A') {
        e.preventDefault();
        cycleAutonomy();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [toggleThinking, cycleAutonomy]);

  if (!status) return null;

  const getProjectName = (path: string) => {
    if (!path) return '';
    const parts = path.replace(/\/$/, '').split('/');
    return parts[parts.length - 1] || path;
  };

  return (
    <div className="flex items-center gap-1.5 px-4 py-1.5 bg-gray-50 border-t border-gray-200 text-xs select-none">
      {/* Mode */}
      <button
        onClick={toggleMode}
        className={`px-2 py-0.5 rounded font-semibold uppercase tracking-wide cursor-pointer transition-colors ${MODE_STYLES[status.mode]}`}
        title="Click to toggle mode"
      >
        {status.mode}
      </button>

      <span className="text-gray-300">|</span>

      {/* Autonomy */}
      <button
        onClick={cycleAutonomy}
        className={`px-2 py-0.5 rounded font-medium cursor-pointer transition-colors ${AUTONOMY_STYLES[status.autonomy_level]}`}
        title="Click to cycle autonomy (Ctrl+Shift+A)"
      >
        {status.autonomy_level}
      </button>

      <span className="text-gray-300">|</span>

      {/* Thinking toggle */}
      <button
        onClick={toggleThinking}
        className={`px-2 py-0.5 rounded font-medium cursor-pointer transition-colors ${
          showThinking ? 'bg-gray-200 text-gray-700 hover:bg-gray-300' : 'bg-gray-100 text-gray-400 hover:bg-gray-200'
        }`}
        title="Toggle thinking visibility (Ctrl+Shift+T)"
      >
        Thinking {showThinking ? 'ON' : 'OFF'}
      </button>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Working dir + git branch */}
      {status.working_dir && (
        <span className="text-gray-400 truncate max-w-[200px]" title={status.working_dir}>
          {getProjectName(status.working_dir)}
          {status.git_branch && (
            <span className="ml-1 text-gray-500">
              <span className="text-gray-300">/</span> {status.git_branch}
            </span>
          )}
        </span>
      )}

      {status.working_dir && status.model && <span className="text-gray-300">|</span>}

      {/* Model */}
      {status.model && (
        <span className="text-gray-500 font-mono truncate max-w-[180px]" title={`${status.model_provider}/${status.model}`}>
          {status.model}
        </span>
      )}
    </div>
  );
}
