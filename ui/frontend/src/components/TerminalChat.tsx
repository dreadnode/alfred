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
    position: 'relative' as const,
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
  'COMMANDS                              type / to see all',
  '',
  '  /analyze-source <URL> "context"   Deep-read a single source',
  '  /detect-llm-writing [file]        Detect LLM writing tells',
  '  /lit-review "topic"               Full literature review',
  '  /peer-review                      Interactive peer review',
  '  /process-peer-review [file]       Respond to a peer review',
  '  /search-sources "query"           Find relevant papers',
  '  /verify-claims section/file.tex   Check claims against evidence',
  '',
  'NATURAL LANGUAGE',
  '',
  '  "build the paper"                   Compile LaTeX → PDF',
  '  "check for errors"                  Validate refs, braces, sync',
  '  "show me the stats"                 Word count, pages, figures',
  '  "add this citation: arXiv:..."      Add to bibliography',
  '  "switch to neurips format"          Change conference template',
  '  "diff against last commit"          Track-changes PDF',
  '  "show reviews"                      List peer review records',
  '',
  '  Or just ask — edit sections, add figures, fix errors, etc.',
]

interface CommandDef {
  name: string
  description: string
  arg_label: string
  args: string
}

export default function TerminalChat() {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)
  const [modelName, setModelName] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [settingsModel, setSettingsModel] = useState('')
  const [settingsApiKey, setSettingsApiKey] = useState('')
  const [settingsApiKeyEnv, setSettingsApiKeyEnv] = useState('')
  const [settingsError, setSettingsError] = useState('')
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [commands, setCommands] = useState<CommandDef[]>([])
  const [cmdHighlight, setCmdHighlight] = useState(0)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const sessionIdRef = useRef<string | null>(null)

  // Fetch model name and commands on mount
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => setModelName(data.model || ''))
      .catch(() => {})
    fetch('/api/commands')
      .then(r => r.json())
      .then(data => setCommands(data))
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

  const { status, send, reconnect } = useWebSocket('/ws/chat', handleWsMessage, handleWsOpen)

  // Focus input when connection is established or processing ends
  useEffect(() => {
    if (status === 'connected' && !isProcessing) {
      inputRef.current?.focus()
    }
  }, [status, isProcessing])

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed || isProcessing || status !== 'connected') return

    addMessage(setMessages, 'user', trimmed)

    if (trimmed === '/help') {
      addMessage(setMessages, 'assistant', WELCOME_LINES.join('\n'))
      setInput('')
      return
    }

    if (trimmed === '/clear') {
      sessionIdRef.current = null
      setMessages([])
      setIsProcessing(false)
      setInput('')
      reconnect()
      return
    }

    if (trimmed.startsWith('/copy')) {
      const countArg = trimmed.slice(5).trim()
      const parsed = countArg ? parseInt(countArg, 10) : 10
      const count = isNaN(parsed) || parsed <= 0 ? 10 : parsed
      const all = messages.filter(m => m.type === 'assistant')
      const selected = all.slice(-count)
      const text = selected.map(m => m.content).join('\n\n')
      if (selected.length === 0) {
        addMessage(setMessages, 'status', 'No agent messages to copy.')
        setInput('')
        return
      }
      navigator.clipboard.writeText(text).then(
        () => addMessage(setMessages, 'status', `Copied ${selected.length} message(s) to clipboard.`),
        () => addMessage(setMessages, 'status', 'Failed to copy to clipboard.'),
      )
      setInput('')
      return
    }

    send(JSON.stringify({ content: trimmed }))
    setInput('')
    setIsProcessing(true)
  }, [input, isProcessing, status, send])

  const handleCancel = useCallback(() => {
    if (!isProcessing || status !== 'connected') return
    send(JSON.stringify({ type: 'cancel' }))
    addMessage(setMessages, 'status', 'Cancelling...')
  }, [isProcessing, status, send])

  // Command autocomplete
  const filteredCommands = input.startsWith('/')
    ? commands.filter(c => c.name.startsWith(input.split(' ')[0]))
    : []
  const showCmdDropdown = filteredCommands.length > 0 && !input.includes(' ')

  const selectCommand = useCallback((cmd: CommandDef) => {
    setInput(cmd.name + ' ')
    setCmdHighlight(0)
  }, [])

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (showCmdDropdown) {
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setCmdHighlight(i => (i > 0 ? i - 1 : filteredCommands.length - 1))
        return
      }
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setCmdHighlight(i => (i < filteredCommands.length - 1 ? i + 1 : 0))
        return
      }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault()
        selectCommand(filteredCommands[cmdHighlight])
        return
      }
      if (e.key === 'Escape') {
        setInput('')
        return
      }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
    if (e.key === 'Escape' && isProcessing) {
      handleCancel()
    }
  }, [handleSubmit, isProcessing, handleCancel, showCmdDropdown, filteredCommands, cmdHighlight, selectCommand])

  const openSettings = useCallback(() => {
    setSettingsModel(modelName)
    setSettingsApiKey('')
    setSettingsApiKeyEnv('')
    setSettingsError('')
    setShowSettings(true)
  }, [modelName])

  const closeSettings = useCallback(() => {
    setShowSettings(false)
    setSettingsError('')
  }, [])

  const saveSettings = useCallback(async () => {
    const model = settingsModel.trim()
    const key = settingsApiKey.trim()
    const env = settingsApiKeyEnv.trim()
    if (!model) { setSettingsError('Model is required'); return }
    if (!key && !env) { setSettingsError('Provide either an API key or an environment variable'); return }
    if (key && !env) { setSettingsError('Environment variable name is required when providing a raw API key'); return }
    setSettingsSaving(true)
    setSettingsError('')
    try {
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, api_key: key, api_key_env: env }),
      })
      const data = await res.json()
      if (data.error) { setSettingsError(data.error); return }
      setModelName(data.model)
      // Clear session and reconnect WS to get a fresh agent with the new model
      sessionIdRef.current = null
      setMessages([])
      setIsProcessing(false)
      setShowSettings(false)
      reconnect()
    } catch (e) {
      setSettingsError(`Failed to save: ${e}`)
    } finally {
      setSettingsSaving(false)
    }
  }, [settingsModel, settingsApiKey, settingsApiKeyEnv, reconnect])

  return (
    <div style={styles.container} onClick={() => inputRef.current?.focus()}>
      {/* Header */}
      <div style={styles.header}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px' }}>
          <span style={styles.headerTitle}>AGENTIC L<span style={{ fontSize: '11px' }}>A</span>T<span style={{ fontSize: '11px' }}>E</span>X</span>
          {modelName && (
            <span
              onClick={openSettings}
              style={{ color: '#4fc3f7', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline', textDecorationStyle: 'dotted' as const, textUnderlineOffset: '3px' }}
              title="Change model settings"
            >{modelName}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span style={{ color: 'var(--dn-text-dim)', fontSize: '11px' }}>
            {status}
          </span>
          <div style={styles.statusDot(status)} />
        </div>
      </div>

      {/* Settings Modal */}
      {showSettings && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 100,
          background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={closeSettings}>
          <div style={{
            background: 'var(--dn-bg-lt, #1e1e1e)', border: '1px solid var(--dn-border-lt, #444)',
            borderRadius: '6px', padding: '20px', width: '340px',
            fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--dn-text, #ccc)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '16px', color: 'var(--dn-accent, #4caf50)' }}>
              Settings
            </div>

            <label style={{ display: 'block', marginBottom: '4px', color: 'var(--dn-text-dim, #888)' }}>Model</label>
            <input
              style={{
                width: '100%', boxSizing: 'border-box' as const, padding: '6px 8px', marginBottom: '12px',
                background: 'var(--dn-bg, #121212)', border: '1px solid var(--dn-border, #333)',
                borderRadius: '3px', color: 'var(--dn-text, #ccc)', fontFamily: 'var(--font-mono)', fontSize: '12px',
              }}
              value={settingsModel}
              onChange={e => setSettingsModel(e.target.value)}
              placeholder="e.g. claude-sonnet-4-20250514"
              autoFocus
            />

            <label style={{ display: 'block', marginBottom: '4px', color: 'var(--dn-text-dim, #888)' }}>API Key</label>
            <input
              style={{
                width: '100%', boxSizing: 'border-box' as const, padding: '6px 8px', marginBottom: '12px',
                background: 'var(--dn-bg, #121212)', border: '1px solid var(--dn-border, #333)',
                borderRadius: '3px', color: 'var(--dn-text, #ccc)', fontFamily: 'var(--font-mono)', fontSize: '12px',
              }}
              value={settingsApiKey}
              onChange={e => setSettingsApiKey(e.target.value)}
              placeholder="sk-ant-..."
            />

            <label style={{ display: 'block', marginBottom: '4px', color: 'var(--dn-text-dim, #888)' }}>API Key Environment Variable</label>
            <input
              style={{
                width: '100%', boxSizing: 'border-box' as const, padding: '6px 8px', marginBottom: '16px',
                background: 'var(--dn-bg, #121212)', border: '1px solid var(--dn-border, #333)',
                borderRadius: '3px', color: 'var(--dn-text, #ccc)', fontFamily: 'var(--font-mono)', fontSize: '12px',
              }}
              value={settingsApiKeyEnv}
              onChange={e => setSettingsApiKeyEnv(e.target.value)}
              placeholder="ANTHROPIC_API_KEY"
            />

            {settingsError && (
              <div style={{ color: 'var(--dn-error, #f44336)', marginBottom: '12px', fontSize: '11px' }}>{settingsError}</div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button onClick={closeSettings} style={{
                background: 'transparent', border: '1px solid var(--dn-border-lt, #444)',
                color: 'var(--dn-text-dim, #888)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                padding: '4px 12px', borderRadius: '3px', cursor: 'pointer',
              }}>CANCEL</button>
              <button onClick={saveSettings} disabled={settingsSaving} style={{
                background: 'var(--dn-accent, #4caf50)', border: 'none',
                color: 'var(--dn-black, #000)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                padding: '4px 12px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700,
                opacity: settingsSaving ? 0.6 : 1,
              }}>{settingsSaving ? 'SAVING...' : 'SAVE'}</button>
            </div>
          </div>
        </div>
      )}

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
            {WELCOME_LINES.map((line, i) => {
              const isHeader = line === WELCOME_LINES[0] || line.startsWith('NATURAL LANGUAGE')
              const cmdMatch = line.match(/^(\s*)(\/\S+)(.*)/)
              return (
                <span key={i}>
                  {i > 0 && '\n'}
                  {isHeader ? <span style={{ color: '#4caf50' }}>{line}</span>
                    : cmdMatch ? <>{cmdMatch[1]}<span style={{ color: '#fff' }}>{cmdMatch[2]}</span>{cmdMatch[3]}</>
                    : line}
                </span>
              )
            })}
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
      <div style={{ position: 'relative' }}>
        {/* Command autocomplete dropdown */}
        {showCmdDropdown && (
          <div style={{
            position: 'absolute', bottom: '100%', left: 0, right: 0, zIndex: 50,
            background: 'var(--dn-bg-lt, #1e1e1e)', border: '1px solid var(--dn-border-lt, #444)',
            borderBottom: 'none', borderRadius: '4px 4px 0 0',
            maxHeight: '200px', overflowY: 'auto',
            fontFamily: 'var(--font-mono)', fontSize: '12px',
          }}>
            {filteredCommands.map((cmd, i) => (
              <div
                key={cmd.name}
                onClick={() => selectCommand(cmd)}
                style={{
                  padding: '6px 12px', cursor: 'pointer',
                  background: i === cmdHighlight ? 'var(--dn-border, #333)' : 'transparent',
                  display: 'flex', justifyContent: 'flex-start', alignItems: 'center',
                }}
              >
                <span style={{ color: 'var(--dn-accent)', minWidth: '180px' }}>{cmd.name}</span>
                <span style={{ color: 'var(--dn-text-dim, #888)', fontSize: '11px' }}>{cmd.description}</span>
              </div>
            ))}
          </div>
        )}
      <div style={styles.inputArea}>
        <span style={styles.prompt}>&gt;</span>
        {!isProcessing && status === 'connected' && input === '' && (
          <span style={styles.cursor} />
        )}
        <input
          ref={inputRef}
          style={styles.input}
          value={input}
          onChange={(e) => { setInput(e.target.value); setCmdHighlight(0) }}
          onKeyDown={handleKeyDown}
          placeholder={
            status !== 'connected' ? 'Connecting...' :
            isProcessing ? 'Agent working...' : ''
          }
          disabled={status !== 'connected' || isProcessing}
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

    </div>
  )
}
