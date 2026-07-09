import { useCallback, useEffect, useRef, useState } from 'react'
import { useWebSocket, ConnectionStatus } from '../hooks/useWebSocket'

// --- Types ---

interface ChatMessage {
  id: string
  type: 'user' | 'assistant' | 'tool_start' | 'tool_end' | 'status' | 'error'
  content: string
  timestamp: number
  meta?: Record<string, unknown>
}

// --- Styles ---

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column' as const,
    height: '100%',
    background: 'var(--dn-bg)',
    borderRight: '1px solid var(--dn-border)',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 16px',
    borderBottom: '1px solid var(--dn-border)',
    background: 'var(--dn-black)',
  },
  headerTitle: {
    color: 'var(--dn-accent)',
    fontSize: '13px',
    fontWeight: 700,
    letterSpacing: '0.05em',
  },
  statusDot: (status: ConnectionStatus) => ({
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: status === 'connected' ? 'var(--dn-success)' :
                status === 'connecting' ? 'var(--dn-warning)' : 'var(--dn-error)',
    boxShadow: status === 'connected' ? '0 0 6px var(--dn-success)' : 'none',
  }),
  messages: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: '12px 16px',
  },
  message: (type: ChatMessage['type']) => ({
    marginBottom: '8px',
    lineHeight: '1.5',
    fontSize: '13px',
    color: type === 'user' ? 'var(--dn-text-bright)' :
           type === 'error' ? 'var(--dn-error)' :
           type === 'tool_start' ? 'var(--dn-text-muted)' :
           type === 'tool_end' ? 'var(--dn-text-muted)' :
           type === 'status' ? 'var(--dn-text-dim)' :
           'var(--dn-text)',
  }),
  prompt: {
    color: 'var(--dn-accent)',
    marginRight: '8px',
  },
  toolBadge: {
    display: 'inline-block',
    padding: '1px 6px',
    borderRadius: '3px',
    background: 'var(--dn-accent-dim)',
    color: 'var(--dn-accent)',
    fontSize: '11px',
    marginRight: '6px',
  },
  inputArea: {
    display: 'flex',
    alignItems: 'center',
    padding: '12px 16px',
    borderTop: '1px solid var(--dn-border)',
    background: 'var(--dn-black)',
  },
  input: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    outline: 'none',
    color: 'var(--dn-text-bright)',
    fontFamily: 'var(--font-mono)',
    fontSize: '13px',
    caretColor: 'var(--dn-accent)',
  },
  cursor: {
    display: 'inline-block',
    width: '8px',
    height: '15px',
    background: 'var(--dn-accent)',
    animation: 'blink 1s step-end infinite',
    verticalAlign: 'text-bottom',
    marginLeft: '2px',
  },
}

// --- Component ---

let msgId = 0
function nextId(): string {
  return `msg-${++msgId}`
}

function addMessage(
  setter: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  type: ChatMessage['type'],
  content: string,
  meta?: Record<string, unknown>,
) {
  setter(prev => [...prev, { id: nextId(), type, content, timestamp: Date.now(), meta }])
}

export default function TerminalChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: nextId(),
      type: 'status',
      content: 'Agentic LaTeX — Terminal ready.',
      timestamp: Date.now(),
    },
  ])
  const [input, setInput] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Process each incoming WebSocket message via callback (no dropped messages)
  const handleWsMessage = useCallback((data: string) => {
    try {
      const event = JSON.parse(data) as Record<string, unknown>
      const type = event.type as string

      switch (type) {
        case 'agent_start':
          addMessage(setMessages, 'status', `Agent started (${event.agent})`)
          break

        case 'step_start':
          addMessage(setMessages, 'status', `--- step ${event.step} ---`)
          break

        case 'generation':
          if (event.content) {
            addMessage(setMessages, 'assistant', event.content as string, event.usage as Record<string, unknown> | undefined)
          }
          break

        case 'tool_start': {
          let argsStr = ''
          try {
            const args = JSON.parse(event.args as string)
            argsStr = Object.entries(args)
              .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
              .join(', ')
          } catch {
            argsStr = (event.args as string) || ''
          }
          if (argsStr.length > 200) argsStr = argsStr.slice(0, 200) + '...'
          addMessage(setMessages, 'tool_start', `${event.tool}(${argsStr})`)
          break
        }

        case 'tool_end': {
          const result = (event.result as string) || ''
          const truncated = result.length > 500 ? result.slice(0, 500) + '...' : result
          addMessage(setMessages, 'tool_end', truncated, { tool: event.tool, stop: event.stop })
          break
        }

        case 'error':
          addMessage(setMessages, 'error', event.message as string)
          break

        case 'stalled':
          addMessage(setMessages, 'status', 'Agent stalled — no tool calls made.')
          break

        case 'reacted':
          addMessage(setMessages, 'status', event.content as string)
          break

        case 'agent_end':
          setIsProcessing(false)
          addMessage(
            setMessages,
            'status',
            `Done (${event.stop_reason}, ${(event.usage as Record<string, number>)?.total_tokens ?? '?'} tokens)`,
          )
          break
      }
    } catch {
      // ignore parse errors
    }
  }, [])

  const { status, send } = useWebSocket('/ws/chat', handleWsMessage)

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed || isProcessing || status !== 'connected') return

    addMessage(setMessages, 'user', trimmed)
    send(JSON.stringify({ content: trimmed }))
    setInput('')
    setIsProcessing(true)
  }, [input, isProcessing, status, send])

  const handleCancel = useCallback(() => {
    if (!isProcessing || status !== 'connected') return
    send(JSON.stringify({ type: 'cancel' }))
    addMessage(setMessages, 'status', 'Cancelling...')
  }, [isProcessing, status, send])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
    if (e.key === 'Escape' && isProcessing) {
      handleCancel()
    }
  }, [handleSubmit, isProcessing, handleCancel])

  return (
    <div style={styles.container}>
      {/* Header */}
      <div style={styles.header}>
        <span style={styles.headerTitle}>AGENTIC LATEX</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ color: 'var(--dn-text-dim)', fontSize: '11px' }}>
            {status}
          </span>
          <div style={styles.statusDot(status)} />
        </div>
      </div>

      {/* Messages */}
      <div style={styles.messages}>
        {messages.map((msg) => (
          <div key={msg.id} style={styles.message(msg.type)}>
            {msg.type === 'user' && (
              <>
                <span style={styles.prompt}>&gt;</span>
                {msg.content}
              </>
            )}
            {msg.type === 'assistant' && (
              <pre style={{ margin: 0, whiteSpace: 'pre-wrap', fontFamily: 'inherit' }}>
                {msg.content}
              </pre>
            )}
            {msg.type === 'tool_start' && (
              <>
                <span style={styles.toolBadge}>TOOL</span>
                {msg.content}
              </>
            )}
            {msg.type === 'tool_end' && (
              <pre style={{
                margin: '0 0 0 12px',
                whiteSpace: 'pre-wrap',
                fontFamily: 'inherit',
                fontSize: '12px',
                color: 'var(--dn-text-dim)',
                maxHeight: '200px',
                overflow: 'auto',
              }}>
                {msg.content}
              </pre>
            )}
            {msg.type === 'status' && (
              <span style={{ fontStyle: 'italic' }}>{msg.content}</span>
            )}
            {msg.type === 'error' && (
              <>
                <span style={{ ...styles.toolBadge, background: 'rgba(239,68,68,0.15)', color: 'var(--dn-error)' }}>
                  ERROR
                </span>
                {msg.content}
              </>
            )}
          </div>
        ))}
        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div style={styles.inputArea}>
        <span style={styles.prompt}>&gt;</span>
        <input
          style={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            status !== 'connected' ? 'Connecting...' :
            isProcessing ? 'Agent working...' : 'Type a message...'
          }
          disabled={status !== 'connected' || isProcessing}
          autoFocus
        />
        {isProcessing && (
          <button
            onClick={handleCancel}
            style={{
              background: 'transparent',
              border: '1px solid var(--dn-border-lt)',
              color: 'var(--dn-error)',
              fontFamily: 'var(--font-mono)',
              fontSize: '11px',
              padding: '2px 8px',
              borderRadius: '3px',
              cursor: 'pointer',
              marginLeft: '8px',
              flexShrink: 0,
            }}
            title="Cancel (Esc)"
          >
            CANCEL
          </button>
        )}
        {!isProcessing && status === 'connected' && input === '' && (
          <span style={styles.cursor} />
        )}
      </div>

    </div>
  )
}
