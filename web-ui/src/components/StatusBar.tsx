import { useEffect } from 'react';
import { useChatStore } from '../stores/chat';
import { apiClient } from '../api/client';

const MODE_STYLES = {
  normal: 'bg-bg-400/40 text-text-200 hover:bg-bg-400/60',
  plan: 'bg-accent-secondary-900 text-accent-secondary-100 hover:bg-accent-secondary-900/80',
} as const;

const AUTONOMY_STYLES = {
  'Manual': 'bg-bg-400/40 text-text-200 hover:bg-bg-400/60',
  'Semi-Auto': 'bg-accent-secondary-900 text-accent-secondary-100 hover:bg-accent-secondary-900/80',
  'Auto': 'bg-success-100/10 text-success-100 hover:bg-success-100/15',
} as const;

const THINKING_STYLES: Record<string, string> = {
  'Off':           'bg-bg-200 text-text-500 hover:bg-bg-300',
  'Low':           'bg-cyan-500/10 text-cyan-600 hover:bg-cyan-500/15',
  'Medium':        'bg-success-100/10 text-success-100 hover:bg-success-100/15',
  'High':          'bg-yellow-500/10 text-yellow-600 hover:bg-yellow-500/15',
  'Self-Critique': 'bg-accent-main-100/10 text-accent-main-100 hover:bg-accent-main-100/15',
} as const;

export function StatusBar() {
  const status = useChatStore(state => state.status);
  const thinkingLevel = useChatStore(state => state.thinkingLevel);
  const toggleMode = useChatStore(state => state.toggleMode);
  const cycleAutonomy = useChatStore(state => state.cycleAutonomy);
  const cycleThinkingLevel = useChatStore(state => state.cycleThinkingLevel);

  // Load initial status on mount
  useEffect(() => {
    const loadStatus = async () => {
      try {
        const configData = await apiClient.getConfig();
        useChatStore.setState({
          thinkingLevel: configData.thinking_level || 'Medium',
        });
        useChatStore.getState().setStatus({
          mode: configData.mode || 'normal',
          autonomy_level: configData.autonomy_level || 'Manual',
          thinking_level: configData.thinking_level || 'Medium',
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
        cycleThinkingLevel();
      }
      if (e.ctrlKey && e.shiftKey && e.key === 'A') {
        e.preventDefault();
        cycleAutonomy();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [cycleThinkingLevel, cycleAutonomy]);

  if (!status) return null;

  const getProjectName = (path: string) => {
    if (!path) return '';
    const parts = path.replace(/\/$/, '').split('/');
    return parts[parts.length - 1] || path;
  };

  return (
    <div className="flex items-center gap-1.5 px-4 py-1.5 bg-bg-000 border-t border-border-300/10 text-xs select-none">
      {/* Mode */}
      <button
        onClick={toggleMode}
        className={`px-1.5 h-5 rounded-md font-semibold uppercase tracking-wide cursor-pointer transition-colors text-[0.625rem] ${MODE_STYLES[status.mode]}`}
        title="Click to toggle mode"
      >
        {status.mode}
      </button>

      <span className="text-text-500">|</span>

      {/* Autonomy */}
      <button
        onClick={cycleAutonomy}
        className={`px-1.5 h-5 rounded-md font-medium cursor-pointer transition-colors text-[0.625rem] ${AUTONOMY_STYLES[status.autonomy_level]}`}
        title="Click to cycle autonomy (Ctrl+Shift+A)"
      >
        {status.autonomy_level}
      </button>

      <span className="text-text-500">|</span>

      {/* Thinking level */}
      <button
        onClick={cycleThinkingLevel}
        className={`px-1.5 h-5 rounded-md font-medium cursor-pointer transition-colors text-[0.625rem] ${THINKING_STYLES[thinkingLevel] || THINKING_STYLES['Medium']}`}
        title="Cycle thinking level (Ctrl+Shift+T)"
      >
        Think: {thinkingLevel}
      </button>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Working dir + git branch */}
      {status.working_dir && (
        <span className="text-text-500 truncate max-w-[200px]" title={status.working_dir}>
          {getProjectName(status.working_dir)}
          {status.git_branch && (
            <span className="ml-1 text-text-400">
              <span className="text-text-500">/</span> {status.git_branch}
            </span>
          )}
        </span>
      )}

      {status.working_dir && status.model && <span className="text-text-500">|</span>}

      {/* Model */}
      {status.model && (
        <span className="text-text-400 font-mono truncate max-w-[180px]" title={`${status.model_provider}/${status.model}`}>
          {status.model}
        </span>
      )}
    </div>
  );
}
