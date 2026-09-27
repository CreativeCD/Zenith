import React from 'react';
import type { TelemetryEvent } from '../types/events';

interface ToolEventProps {
  event: TelemetryEvent;
  isLast?: boolean;
  prefixChar?: string; // '├─' or '└─'
}

export const ToolEvent: React.FC<ToolEventProps> = ({
  event,
  prefixChar = '├─',
}) => {
  const tool = event.tool || 'unknown_tool';
  const args = event.tool_args || {};

  // Concise formatting of tool arguments matching CLI style
  const formatToolCall = () => {
    switch (tool) {
      case 'search_code': {
        const query = args.query ? `"${args.query}"` : '';
        const path = args.path ? `, "${args.path}"` : '';
        return `search_code(${query}${path})`;
      }
      case 'get_symbol': {
        const sym = args.symbol_name ? `"${args.symbol_name}"` : '';
        const file = args.file_path ? ` in ${args.file_path}` : '';
        return `get_symbol(${sym})${file}`;
      }
      case 'find_references': {
        const sym = args.symbol_name ? `"${args.symbol_name}"` : '';
        return `find_references(${sym})`;
      }
      case 'apply_patch': {
        const file = args.file_path || 'file';
        return `apply_patch → ${file}`;
      }
      case 'read_file_range': {
        const file = args.file_path || 'file';
        const start = args.start_line ?? 1;
        const end = args.end_line ?? 50;
        return `read_file_range(${file}:${start}-${end})`;
      }
      case 'write_file': {
        const file = args.file_path || 'file';
        return `write_file(${file})`;
      }
      case 'run_test_suite': {
        const filter = args.test_filter ? `"${args.test_filter}"` : '';
        return `run_tests(${filter})`;
      }
      case 'run_bash_sandboxed': {
        const cmd = args.command ? `"${args.command}"` : '';
        return `bash(${cmd})`;
      }
      case 'git_diff': {
        return `git_diff(${args.file_path || 'HEAD'})`;
      }
      default:
        if (Object.keys(args).length > 0) {
          const firstVal = Object.values(args)[0];
          return `${tool}("${String(firstVal)}")`;
        }
        return `${tool}()`;
    }
  };

  const isSuccess = event.result_status === 'SUCCESS';
  const isFail = event.result_status === 'FAIL';

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'baseline',
        gap: '8px',
        paddingLeft: '16px',
        lineHeight: '22px',
        fontFamily: 'var(--font-mono)',
        fontSize: '12px',
        color: 'var(--text-code)',
      }}
    >
      <span style={{ color: 'var(--text-muted)', userSelect: 'none' }}>{prefixChar}</span>
      <span style={{ color: 'var(--text-primary)' }}>{formatToolCall()}</span>

      {event.latency_ms !== undefined && event.latency_ms > 0 && (
        <span style={{ color: 'var(--text-muted)', fontSize: '11px', marginLeft: '6px' }}>
          {event.latency_ms}ms
        </span>
      )}

      {isSuccess && (
        <span style={{ color: 'var(--status-success)', fontSize: '11px', marginLeft: 'auto' }}>
          ✓
        </span>
      )}
      {isFail && (
        <span style={{ color: 'var(--status-fail)', fontSize: '11px', marginLeft: 'auto' }}>
          ✕
        </span>
      )}
    </div>
  );
};
