import React, { useState } from 'react';
import type { DiffResponse, FileDiff } from '../types/agent';
import { DiffEditor } from '@monaco-editor/react';

interface DiffViewerProps {
  diffData: DiffResponse | null;
  onClose: () => void;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ diffData, onClose }) => {
  const files = diffData?.files || [];
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [useMonaco, setUseMonaco] = useState(true);

  const selectedFile: FileDiff | undefined = files[selectedIndex];

  // Parse diff into original and modified text for Monaco DiffEditor
  const getOriginalAndModified = (diff: string) => {
    const origLines: string[] = [];
    const modLines: string[] = [];

    diff.split('\n').forEach((line) => {
      if (line.startsWith('---') || line.startsWith('+++') || line.startsWith('@@')) {
        return;
      }
      if (line.startsWith('-')) {
        origLines.push(line.slice(1));
      } else if (line.startsWith('+')) {
        modLines.push(line.slice(1));
      } else {
        const content = line.startsWith(' ') ? line.slice(1) : line;
        origLines.push(content);
        modLines.push(content);
      }
    });

    return {
      original: origLines.join('\n'),
      modified: modLines.join('\n'),
    };
  };

  const { original, modified } = selectedFile
    ? getOriginalAndModified(selectedFile.diff)
    : { original: '', modified: '' };

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(9, 10, 12, 0.85)',
        backdropFilter: 'blur(3px)',
        zIndex: 50,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '32px',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '1080px',
          height: '80vh',
          backgroundColor: 'var(--bg-surface)',
          border: '1px solid var(--border-medium)',
          borderRadius: '6px',
          display: 'flex',
          flexDirection: 'column',
          boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
          overflow: 'hidden',
        }}
      >
        {/* Diff Top Bar */}
        <div
          style={{
            padding: '12px 18px',
            borderBottom: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            backgroundColor: 'var(--bg-primary)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                padding: '2px 6px',
                borderRadius: '3px',
                backgroundColor: 'rgba(234, 179, 8, 0.12)',
                color: '#eab308',
                fontWeight: 600,
                letterSpacing: '0.04em',
              }}
            >
              MODIFIED
            </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '13px',
                color: 'var(--text-primary)',
                fontWeight: 500,
              }}
            >
              {selectedFile ? selectedFile.path : 'billing/discounts.py'}
            </span>
          </div>

          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            {selectedFile && (
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  color: 'var(--text-muted)',
                }}
              >
                <span style={{ color: 'var(--diff-add-text)' }}>+{selectedFile.additions || 1}</span>{' '}
                <span style={{ color: 'var(--diff-del-text)' }}>-{selectedFile.deletions || 1}</span>
              </span>
            )}

            <button
              onClick={() => setUseMonaco(!useMonaco)}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '11px',
                color: 'var(--text-secondary)',
                padding: '3px 8px',
                borderRadius: '3px',
                border: '1px solid var(--border-subtle)',
                cursor: 'pointer',
              }}
            >
              {useMonaco ? 'terminal diff' : 'monaco diff'}
            </button>

            <button
              onClick={onClose}
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
                color: 'var(--text-muted)',
                padding: '3px 8px',
                cursor: 'pointer',
              }}
            >
              Esc [×]
            </button>
          </div>
        </div>

        {/* File Tabs if multiple files */}
        {files.length > 1 && (
          <div
            style={{
              display: 'flex',
              gap: '4px',
              padding: '6px 16px',
              borderBottom: '1px solid var(--border-subtle)',
              backgroundColor: 'var(--bg-surface-elevated)',
              overflowX: 'auto',
            }}
          >
            {files.map((file, idx) => (
              <button
                key={file.path}
                onClick={() => setSelectedIndex(idx)}
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '11px',
                  padding: '4px 10px',
                  borderRadius: '3px',
                  color: idx === selectedIndex ? 'var(--text-primary)' : 'var(--text-muted)',
                  backgroundColor: idx === selectedIndex ? 'var(--bg-surface-active)' : 'transparent',
                  border: idx === selectedIndex ? '1px solid var(--border-medium)' : '1px solid transparent',
                  cursor: 'pointer',
                }}
              >
                {file.path}
              </button>
            ))}
          </div>
        )}

        {/* Diff Content Area */}
        <div style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
          {useMonaco ? (
            <DiffEditor
              height="100%"
              theme="vs-dark"
              language="python"
              original={original || "def calculate_discount(customer: dict):\n    tier = customer['tier']\n    return TIER_DISCOUNTS.get(str(tier).lower(), 0.0)"}
              modified={modified || "def calculate_discount(customer: dict):\n    tier = customer.get('tier')\n    if tier is None:\n        return 0.0\n    return TIER_DISCOUNTS.get(str(tier).lower(), 0.0)"}
              options={{
                readOnly: true,
                renderSideBySide: true,
                fontSize: 12,
                fontFamily: 'JetBrains Mono, monospace',
                minimap: { enabled: false },
                scrollBeyondLastLine: false,
                lineNumbers: 'on',
              }}
            />
          ) : (
            <div
              style={{
                height: '100%',
                overflowY: 'auto',
                padding: '16px',
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
                lineHeight: '20px',
                backgroundColor: 'var(--bg-primary)',
              }}
            >
              {(selectedFile?.diff || diffData?.full_diff || "@@ -38,3 +38,4 @@\n-    tier = customer['tier']\n+    tier = customer.get('tier')\n+    if tier is None: return 0.0")
                .split('\n')
                .map((line, idx) => {
                  let bg = 'transparent';
                  let color = 'var(--text-primary)';
                  if (line.startsWith('+') && !line.startsWith('+++')) {
                    bg = 'var(--diff-add-bg)';
                    color = 'var(--diff-add-text)';
                  } else if (line.startsWith('-') && !line.startsWith('---')) {
                    bg = 'var(--diff-del-bg)';
                    color = 'var(--diff-del-text)';
                  } else if (line.startsWith('@@')) {
                    color = 'var(--text-muted)';
                  }

                  return (
                    <div
                      key={idx}
                      style={{
                        backgroundColor: bg,
                        color,
                        padding: '1px 8px',
                        whiteSpace: 'pre-wrap',
                      }}
                    >
                      {line}
                    </div>
                  );
                })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
