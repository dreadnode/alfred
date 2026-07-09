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

const WELCOME_LINES = [
  'WHAT YOU CAN ASK',
  '',
  '  "build the paper"                   Compile LaTeX → PDF',
  '  "check for errors"                  Validate refs, braces, sync',
  '  "show me the stats"                 Word count, pages, figures',
  '  "search for papers on X"            Search Semantic Scholar',
  '  "add this citation: arXiv:..."      Add to bibliography',
  '  "switch to neurips format"          Change conference template',
  '  "diff against last commit"          Track-changes PDF',
  '  "show reviews"                      List peer review records',
  '',
  '  "find papers about X"               Web search for sources',
  '  "read this page: <URL>"             Fetch and summarize a URL',
  '  "literature review on X"            Full search → analyze → report',
  '  "verify claims in the intro"        Check claims against evidence',
  '  "review my paper"                   Interactive peer review',
  '',
  '  Or just ask — edit sections, add figures, fix errors, etc.',
]

export default function TerminalChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)
  const [modelName, setModelName] = useState('')
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const sessionIdRef = useRef<string | null>(null)

  // Fetch model name from server config on mount
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => setModelName(data.model || ''))
      .catch(() => {})
  }, [])

  // Convert a server event to a ChatMessage (without setting state)
  const eventToMessage = useCallback((event: Record<string, unknown>): ChatMessage | null => {
    const type = event.type as string

    switch (type) {
      case 'user_message':
        return { id: nextId(), type: 'user', content: event.content as string, timestamp: Date.now() }

      case 'agent_start':
        return { id: nextId(), type: 'status', content: `Agent started (${event.agent})`, timestamp: Date.now() }

      case 'step_start':
        return { id: nextId(), type: 'status', content: `--- step ${event.step} ---`, timestamp: Date.now() }

      case 'generation':
        if (event.content) {
          return { id: nextId(), type: 'assistant', content: event.content as string, timestamp: Date.now(), meta: event.usage as Record<string, unknown> | undefined }
        }
        return null

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
        return { id: nextId(), type: 'tool_start', content: `${event.tool}(${argsStr})`, timestamp: Date.now() }
      }

      case 'tool_end': {
        const result = (event.result as string) || ''
        const truncated = result.length > 500 ? result.slice(0, 500) + '...' : result
        return { id: nextId(), type: 'tool_end', content: truncated, timestamp: Date.now(), meta: { tool: event.tool, stop: event.stop } }
      }

      case 'error':
        return { id: nextId(), type: 'error', content: event.message as string, timestamp: Date.now() }

      case 'stalled':
        return { id: nextId(), type: 'status', content: 'Agent stalled — no tool calls made.', timestamp: Date.now() }

      case 'reacted':
        return { id: nextId(), type: 'status', content: event.content as string, timestamp: Date.now() }

      case 'agent_end':
        return {
          id: nextId(), type: 'status', timestamp: Date.now(),
          content: `Done (${event.stop_reason}, ${(event.usage as Record<string, number>)?.total_tokens ?? '?'} tokens)`,
        }

      default:
        return null
    }
  }, [])

  // Handle incoming WebSocket messages
  const handleWsMessage = useCallback((data: string) => {
    try {
      const event = JSON.parse(data) as Record<string, unknown>
      const type = event.type as string

      if (type === 'session_start') {
        const prevId = sessionIdRef.current
        sessionIdRef.current = event.session_id as string
        if (event.resumed) {
          addMessage(setMessages, 'status', 'Session resumed.')
        } else if (prevId) {
          // Had a session but it expired — clear stale messages
          setIsProcessing(false)
          setMessages([{
            id: nextId(),
            type: 'status',
            content: 'Previous session expired. Starting fresh.',
            timestamp: Date.now(),
          }])
        }
        return
      }

      if (type === 'history') {
        // Batch-replay: convert all events to messages in one pass
        const events = event.events as Record<string, unknown>[]
        const restored: ChatMessage[] = [{
          id: nextId(),
          type: 'status',
          content: 'Agentic LaTeX — Session restored.',
          timestamp: Date.now(),
        }]
        const lastType = events.length > 0 ? (events[events.length - 1] as Record<string, unknown>).type : null
        for (const histEvent of events) {
          const msg = eventToMessage(histEvent)
          if (msg) restored.push(msg)
        }
        setMessages(restored)
        // If history ends with agent_end, agent is not running
        if (lastType === 'agent_end') setIsProcessing(false)
        return
      }

      const msg = eventToMessage(event)
      if (msg) {
        if (type === 'agent_end') setIsProcessing(false)
        setMessages(prev => [...prev, msg])
      }
    } catch {
      // ignore parse errors
    }
  }, [eventToMessage])

  // On WebSocket (re)connect, send resume with session ID
  const handleWsOpen = useCallback((sendFn: (data: string) => void) => {
    if (sessionIdRef.current) {
      sendFn(JSON.stringify({ type: 'resume', session_id: sessionIdRef.current }))
    } else {
      // New session — send an empty init so the server assigns an ID
      sendFn(JSON.stringify({ type: 'init' }))
    }
  }, [])

  const { status, send } = useWebSocket('/ws/chat', handleWsMessage, handleWsOpen)

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
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
          <span style={styles.headerTitle}>AGENTIC L<span style={{ fontSize: '11px' }}>A</span>T<span style={{ fontSize: '11px' }}>E</span>X</span>
          {modelName && (
            <span style={{ color: '#4fc3f7', fontSize: '11px' }}>{modelName}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ color: 'var(--dn-text-dim)', fontSize: '11px' }}>
            {status}
          </span>
          <div style={styles.statusDot(status)} />
        </div>
      </div>

      {/* Messages */}
      <div style={styles.messages}>
        {messages.length === 0 && (
          <pre style={{
            margin: 0,
            fontFamily: 'inherit',
            fontSize: '12px',
            lineHeight: '1.6',
            color: 'var(--dn-text-dim)',
            whiteSpace: 'pre',
          }}>
            <span style={{ color: '#4caf50' }}>{WELCOME_LINES[0]}</span>
            {'\n' + WELCOME_LINES.slice(1).join('\n')}
          </pre>
        )}
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
        {!isProcessing && status === 'connected' && input === '' && (
          <span style={styles.cursor} />
        )}
        <input
          style={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={
            status !== 'connected' ? 'Connecting...' :
            isProcessing ? 'Agent working...' : ''
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
      </div>

    </div>
  )
}
