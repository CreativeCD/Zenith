import React, { useState, useEffect } from 'react';
import { useAgentStream } from '../hooks/useAgentStream';
import { useRun } from '../hooks/useRun';
import { useVerification } from '../hooks/useVerification';
import { ZenithHeader } from './ZenithHeader';
import { IssueInput } from './IssueInput';
import { AgentStream } from './AgentStream';
import { RepositoryContext } from './RepositoryContext';
import { DiffViewer } from './DiffViewer';
import { CommandPalette } from './CommandPalette';

export const ZenithShell: React.FC = () => {
  const { events, harnessState, fetchStatus, clearEvents } = useAgentStream();
  const [currentIssue, setCurrentIssue] = useState<string>('');
  const [isDiffOpen, setIsDiffOpen] = useState(false);
  const [isCommandPaletteOpen, setIsCommandPaletteOpen] = useState(false);

  const { startRun, stopRun, isRunning, error } = useRun(() => {
    fetchStatus();
  });

  const { diffData, fetchDiff, runVerification } = useVerification();

  // Listen for global Cmd+K or Ctrl+K
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        setIsCommandPaletteOpen((prev) => !prev);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleStartRun = (issueText: string, options?: { dryRun?: boolean; devDemo?: boolean }) => {
    setCurrentIssue(issueText);
    clearEvents();
    startRun({
      issue: issueText,
      repo: harnessState.repo_path,
      dry_run: options?.dryRun,
      dev_demo: options?.devDemo,
    });
  };

  const handleOpenDiff = async () => {
    await fetchDiff();
    setIsDiffOpen(true);
  };

  const handleManualVerification = async () => {
    await runVerification(harnessState.repo_path);
  };

  const handleInspectRepo = () => {
    handleStartRun(currentIssue || 'Inspect repository and verify system state.', { dryRun: true });
  };

  const handleRestartRun = () => {
    handleStartRun(currentIssue || 'Fix the KeyError when calling calculate_discount() with missing customer tier', { devDemo: true });
  };

  const commands = [
    {
      id: 'run-issue',
      label: 'Run current issue',
      shortcut: '↵',
      description: 'Trigger autonomous agent execution on current issue',
      action: () => handleStartRun(currentIssue || 'Fix customer tier KeyError', { devDemo: true }),
    },
    {
      id: 'inspect-repo',
      label: 'Inspect repository',
      shortcut: '⌘I',
      description: 'Execute AST parsing and semantic repository indexing (0-token dry run)',
      action: handleInspectRepo,
    },
    {
      id: 'view-diff',
      label: 'View diff',
      shortcut: '⌘D',
      description: 'Open contextual git diff viewer for modified files',
      action: handleOpenDiff,
    },
    {
      id: 'run-verification',
      label: 'Run verification',
      shortcut: '⌘V',
      description: 'Trigger 6-phase deterministic verification gate directly',
      action: handleManualVerification,
    },
    {
      id: 'stop-agent',
      label: 'Stop agent',
      shortcut: '⌘.',
      description: 'Halt active agent run immediately',
      action: stopRun,
    },
    {
      id: 'restart-run',
      label: 'Restart run',
      shortcut: '⌘R',
      description: 'Clear history and restart recovery sequence',
      action: handleRestartRun,
    },
  ];

  const hasEvents = events.length > 0;

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100vh',
        width: '100vw',
        backgroundColor: 'var(--bg-primary)',
        color: 'var(--text-primary)',
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {/* Top minimal header */}
      <ZenithHeader
        repoPath={harnessState.repo_path}
        gitBranch={harnessState.git_branch}
        status={harnessState.status}
        currentStep={harnessState.current_step}
        onOpenCommandPalette={() => setIsCommandPaletteOpen(true)}
        onToggleDiff={handleOpenDiff}
        hasDiff={Boolean(diffData && diffData.files.length > 0)}
      />

      {/* Main workspace */}
      <main
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* If no events yet, show clean empty initial workspace */}
        {!hasEvents && !isRunning ? (
          <div
            style={{
              flex: 1,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              position: 'relative',
              userSelect: 'none',
            }}
          >
            {/* Subtle center placeholder or empty canvas */}
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
                color: 'var(--text-muted)',
                letterSpacing: '0.04em',
                opacity: 0.25,
              }}
            >
              zenith harness ready
            </div>

            {/* Subtle lower-right status indicator */}
            <RepositoryContext status={harnessState.status} verificationEnabled={true} />
          </div>
        ) : (
          /* Execution Stream View */
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
            <AgentStream
              events={events}
              verificationPhases={harnessState.verification}
              activeIssue={currentIssue || harnessState.active_issue}
              currentStep={harnessState.current_step}
              isRunning={harnessState.status === 'RUNNING'}
            />
          </div>
        )}

        {/* Bottom Error banner if any */}
        {error && (
          <div
            style={{
              padding: '6px 24px',
              backgroundColor: 'var(--diff-del-bg)',
              color: 'var(--diff-del-text)',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              borderTop: '1px solid var(--diff-del-border)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'space-between',
            }}
          >
            <span>✕ {error}</span>
          </div>
        )}

        {/* Bottom Terminal Prompt Issue Input */}
        <IssueInput
          onSubmit={handleStartRun}
          isRunning={harnessState.status === 'RUNNING'}
          initialValue={currentIssue}
        />
      </main>

      {/* Git Diff Viewer Modal */}
      {isDiffOpen && (
        <DiffViewer
          diffData={diffData}
          onClose={() => setIsDiffOpen(false)}
        />
      )}

      {/* Command Palette Modal */}
      <CommandPalette
        isOpen={isCommandPaletteOpen}
        onClose={() => setIsCommandPaletteOpen(false)}
        commands={commands}
      />
    </div>
  );
};
