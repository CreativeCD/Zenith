import React, { useState, useRef, useEffect } from 'react';

interface IssueInputProps {
  onSubmit: (issueText: string, options?: { dryRun?: boolean; devDemo?: boolean }) => void;
  isRunning: boolean;
  disabled?: boolean;
  initialValue?: string;
}

export const IssueInput: React.FC<IssueInputProps> = ({
  onSubmit,
  isRunning,
  disabled = false,
  initialValue = '',
}) => {
  const [value, setValue] = useState(initialValue);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (initialValue && !value) {
      setValue(initialValue);
    }
  }, [initialValue]);

  // Auto-resize textarea height
  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 180)}px`;
    }
  }, [value]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = () => {
    if (isRunning || disabled) return;
    const trimmed = value.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
  };

  const handleRunDemo = () => {
    if (isRunning || disabled) return;
    const prompt = value.trim() || 'Fix the KeyError when calling calculate_discount() with missing customer tier';
    setValue(prompt);
    onSubmit(prompt, { devDemo: true });
  };

  return (
    <div
      style={{
        width: '100%',
        maxWidth: '920px',
        margin: '0 auto',
        padding: '0 24px 20px 24px',
      }}
    >
      <div
        style={{
          border: '1px solid var(--border-medium)',
          borderRadius: '4px',
          backgroundColor: 'var(--bg-surface)',
          padding: '12px 16px',
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          boxShadow: '0 2px 8px rgba(0, 0, 0, 0.35)',
          transition: 'border-color 0.15s ease',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: '10px' }}>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '14px',
              color: 'var(--text-muted)',
              lineHeight: '22px',
              userSelect: 'none',
            }}
          >
            ›
          </span>
          <textarea
            ref={textareaRef}
            rows={1}
            value={value}
            disabled={isRunning || disabled}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Describe an issue, paste an error, or ask Zenith to inspect…"
            style={{
              flex: 1,
              fontFamily: 'var(--font-mono)',
              fontSize: '13px',
              lineHeight: '22px',
              color: 'var(--text-primary)',
              resize: 'none',
              backgroundColor: 'transparent',
              minHeight: '22px',
              maxHeight: '180px',
            }}
          />
        </div>

        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            borderTop: '1px solid var(--border-subtle)',
            paddingTop: '8px',
            marginTop: '4px',
          }}
        >
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              color: 'var(--text-muted)',
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
            }}
          >
            <span>
              <span style={{ color: 'var(--text-secondary)' }}>Enter</span> to run
            </span>
            <span>
              <span style={{ color: 'var(--text-secondary)' }}>Shift+Enter</span> newline
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <button
              onClick={handleRunDemo}
              disabled={isRunning || disabled}
              title="Run sample recovery issue with real verification gate"
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                color: 'var(--text-secondary)',
                padding: '4px 10px',
                borderRadius: '3px',
                border: '1px solid var(--border-subtle)',
                backgroundColor: 'transparent',
                cursor: (isRunning || disabled) ? 'not-allowed' : 'pointer',
                opacity: (isRunning || disabled) ? 0.5 : 1,
              }}
            >
              load sample
            </button>

            <button
              onClick={handleSubmit}
              disabled={isRunning || disabled || !value.trim()}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                fontWeight: 600,
                color: isRunning ? 'var(--text-muted)' : 'var(--text-primary)',
                padding: '4px 12px',
                borderRadius: '3px',
                border: '1px solid var(--border-medium)',
                backgroundColor: isRunning ? 'transparent' : 'var(--bg-surface-elevated)',
                cursor: (isRunning || disabled || !value.trim()) ? 'not-allowed' : 'pointer',
                transition: 'all 0.15s ease',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '6px',
              }}
            >
              {isRunning ? (
                <>
                  <span className="animate-pulse-slow">◌</span>
                  <span>Running…</span>
                </>
              ) : (
                <>
                  <span>Run Agent</span>
                  <span style={{ fontSize: '10px', opacity: 0.6 }}>↵</span>
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
