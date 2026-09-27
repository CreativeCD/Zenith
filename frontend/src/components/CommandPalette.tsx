import React, { useState, useEffect, useRef } from 'react';

interface CommandItem {
  id: string;
  label: string;
  shortcut?: string;
  description?: string;
  action: () => void;
}

interface CommandPaletteProps {
  isOpen: boolean;
  onClose: () => void;
  commands: CommandItem[];
}

export const CommandPalette: React.FC<CommandPaletteProps> = ({
  isOpen,
  onClose,
  commands,
}) => {
  const [search, setSearch] = useState('');
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  const filteredCommands = commands.filter((cmd) =>
    cmd.label.toLowerCase().includes(search.toLowerCase()) ||
    (cmd.description && cmd.description.toLowerCase().includes(search.toLowerCase()))
  );

  useEffect(() => {
    if (isOpen) {
      setSearch('');
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  useEffect(() => {
    setSelectedIndex(0);
  }, [search]);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (!isOpen) return;

      if (e.key === 'Escape') {
        e.preventDefault();
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev + 1) % (filteredCommands.length || 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => (prev - 1 + filteredCommands.length) % (filteredCommands.length || 1));
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (filteredCommands[selectedIndex]) {
          filteredCommands[selectedIndex].action();
          onClose();
        }
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, filteredCommands, selectedIndex, onClose]);

  if (!isOpen) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(9, 10, 12, 0.75)',
        backdropFilter: 'blur(2px)',
        zIndex: 100,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        paddingTop: '15vh',
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        style={{
          width: '100%',
          maxWidth: '540px',
          backgroundColor: 'var(--bg-surface)',
          border: '1px solid var(--border-medium)',
          borderRadius: '6px',
          boxShadow: '0 16px 40px rgba(0, 0, 0, 0.65)',
          overflow: 'hidden',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            padding: '12px 16px',
            borderBottom: '1px solid var(--border-subtle)',
            display: 'flex',
            alignItems: 'center',
            gap: '10px',
          }}
        >
          <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>›</span>
          <input
            ref={inputRef}
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Type a command or search…"
            style={{
              width: '100%',
              fontFamily: 'var(--font-mono)',
              fontSize: '13px',
              color: 'var(--text-primary)',
            }}
          />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: '11px', color: 'var(--text-muted)' }}>
            ESC
          </span>
        </div>

        <div style={{ maxHeight: '280px', overflowY: 'auto', padding: '6px' }}>
          {filteredCommands.length === 0 ? (
            <div
              style={{
                padding: '12px 16px',
                fontFamily: 'var(--font-mono)',
                fontSize: '12px',
                color: 'var(--text-muted)',
              }}
            >
              No matching commands
            </div>
          ) : (
            filteredCommands.map((cmd, idx) => {
              const isSelected = idx === selectedIndex;
              return (
                <div
                  key={cmd.id}
                  onClick={() => {
                    cmd.action();
                    onClose();
                  }}
                  onMouseEnter={() => setSelectedIndex(idx)}
                  style={{
                    padding: '8px 12px',
                    borderRadius: '4px',
                    backgroundColor: isSelected ? 'var(--bg-surface-active)' : 'transparent',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    cursor: 'pointer',
                    transition: 'background 0.1s ease',
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '12px',
                        color: isSelected ? 'var(--text-primary)' : 'var(--text-secondary)',
                        fontWeight: isSelected ? 500 : 400,
                      }}
                    >
                      {cmd.label}
                    </div>
                    {cmd.description && (
                      <div
                        style={{
                          fontSize: '11px',
                          color: 'var(--text-muted)',
                          marginTop: '2px',
                        }}
                      >
                        {cmd.description}
                      </div>
                    )}
                  </div>

                  {cmd.shortcut && (
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontSize: '10px',
                        color: 'var(--text-muted)',
                        padding: '2px 5px',
                        border: '1px solid var(--border-subtle)',
                        borderRadius: '3px',
                      }}
                    >
                      {cmd.shortcut}
                    </span>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
