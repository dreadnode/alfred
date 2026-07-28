import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { useWebSocket, ConnectionStatus } from '../hooks/useWebSocket'

// --- Types ---

interface ChatMessage {
  id: string
  type: 'user' | 'assistant' | 'tool_start' | 'tool_end' | 'status' | 'error' | 'help'
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
    color: 'var(--al-brand)',
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
    color: 'var(--al-interactive)',
    marginRight: '8px',
    lineHeight: '1.5',
  },
  toolBadge: {
    display: 'inline-block',
    padding: '1px 6px',
    borderRadius: '3px',
    background: 'rgba(79, 195, 247, 0.15)',
    color: '#4fc3f7',
    fontSize: '11px',
    marginRight: '6px',
  },
  inputArea: {
    display: 'flex',
    alignItems: 'flex-start',
    padding: '12px 16px',
    borderTop: '1px solid var(--dn-border)',
    background: 'var(--dn-black)',
    position: 'relative' as const,
  },
  input: {
    flex: 1,
    background: 'transparent',
    border: 'none',
    outline: 'none',
    color: 'var(--dn-text-bright)',
    fontFamily: 'var(--font-mono)',
    fontSize: '13px',
    caretColor: 'var(--al-interactive)',
    resize: 'none' as const,
    overflow: 'hidden',
    lineHeight: '1.5',
    padding: 0,
    minHeight: '20px',
  },
  cursor: {
    display: 'inline-block',
    width: '8px',
    height: '15px',
    background: 'var(--al-interactive)',
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

const CLIENT_COMMANDS = [
  { name: '/clear', description: 'Reset session and start fresh' },
  { name: '/copy [N]', description: 'Copy last N agent messages (default 10)' },
  { name: '/help', description: 'Show this guide' },
  { name: '/load-pdf <path>', description: 'Load an external PDF into viewer' },
  { name: '/reset-pdf', description: 'Reset viewer to built paper' },
]

const NATURAL_LANGUAGE_LINES = [
  '"build the paper"                   Compile LaTeX → PDF',
  '"check for errors"                  Validate refs, braces, sync',
  '"show me the stats"                 Word count, pages, figures',
  '"add this citation: arXiv:..."      Add to bibliography',
  '"switch to neurips format"          Change conference template',
  '"diff against last commit"          Track-changes PDF',
  '"show reviews"                      List peer review records',
]

function buildWelcomeLines(commands: { name: string; description: string; args?: string; arg_label?: string }[]): string[] {
  // Build command lines with usage hint from arg_label
  const cmdLines = commands.map(c => {
    let usage = c.name
    if (c.arg_label) {
      const isOptional = c.args === 'optional'
      usage += isOptional ? ` [${c.arg_label}]` : ` <${c.arg_label}>`
    }
    return { usage, desc: c.description }
  })

  // Add client commands
  CLIENT_COMMANDS.forEach(c => cmdLines.push({ usage: c.name, desc: c.description }))

  // Compute alignment column
  const maxUsage = Math.max(...cmdLines.map(c => c.usage.length))
  const col = maxUsage + 3

  const lines: string[] = [
    'COMMANDS                              type / to see all',
    '',
    ...cmdLines.map(c => `  ${c.usage.padEnd(col)}${c.desc}`),
    '',
    'NATURAL LANGUAGE',
    '',
    ...NATURAL_LANGUAGE_LINES.map(l => `  ${l}`),
    '',
    '  Or just ask — edit sections, add figures, fix errors, etc.',
  ]
  return lines
}

interface CommandDef {
  name: string
  description: string
  arg_label: string
  args: string
}

interface TerminalChatProps {
  headerExtra?: React.ReactNode
}

export default function TerminalChat({ headerExtra }: TerminalChatProps = {}) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [promptHistory] = useState<string[]>(() => {
    try {
      const parsed = JSON.parse(localStorage.getItem('prompt-history') || '[]')
      return Array.isArray(parsed) ? parsed : []
    } catch { return [] }
  })
  const historyIndexRef = useRef(-1)
  const [isProcessing, setIsProcessing] = useState(false)
  const [modelName, setModelName] = useState('')
  const [appVersion, setAppVersion] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [settingsModel, setSettingsModel] = useState('')
  const [settingsApiKey, setSettingsApiKey] = useState('')
  const [settingsApiKeyEnv, setSettingsApiKeyEnv] = useState('')
  const [settingsError, setSettingsError] = useState('')
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [commands, setCommands] = useState<CommandDef[]>([])
  const [cmdHighlight, setCmdHighlight] = useState(0)
  const welcomeLines = useMemo(() => buildWelcomeLines(commands), [commands])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const sessionIdRef = useRef<string | null>(null)

  // Fetch model name and commands on mount
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => { setModelName(data.model || ''); setAppVersion(data.version || '') })
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
      case 'step_start':
        return null

      case 'generation':
        if (event.content) {
          return { id: nextId(), type: 'assistant', content: event.content as string, timestamp: Date.now(), meta: event.usage as Record<string, unknown> | undefined }
        }
        return null

      case 'tool_start': {
        const tool = (event.tool as string) || 'unknown'
        if (tool === 'finish_task' || tool === 'give_up_on_task') return null
        let summary = tool
        try {
          const args = JSON.parse(event.args as string)
          const labels: Record<string, (a: Record<string, unknown>) => string> = {
            build_paper: () => 'Building paper...',
            sync_paper: () => 'Syncing paper.yaml → main.tex...',
            validate_paper: () => 'Validating paper...',
            search_citations: a => `Searching citations: "${a.query || ''}"`,
            add_citation: a => `Adding citation: ${a.paper_id || '?'}`,
            paper_stats: () => 'Getting paper stats...',
            generate_diff: a => `Generating diff${a.rev ? ` vs ${a.rev}` : ''}...`,
            switch_template: a => `Switching template to ${a.template || '?'}...`,
            list_templates: () => 'Listing templates...',
            list_reviews: () => 'Listing reviews...',
            web_search: a => `Searching: "${a.query || ''}"`,
            web_fetch: a => { const u = String(a.url || ''); return `Fetching: ${u.slice(0, 60)}${u.length > 60 ? '...' : ''}` },
            read_file: a => `Reading ${a.path || a.file_path || 'file'}`,
            write_file: a => `Writing ${a.path || a.file_path || 'file'}`,
            command: a => { const c = Array.isArray(a.cmd) ? a.cmd.join(' ') : String(a.cmd || ''); return `Running: ${c.slice(0, 80)}${c.length > 80 ? '...' : ''}` },
          }
          summary = labels[tool]?.(args) ?? `${tool}...`
        } catch {
          summary = `${tool}...`
        }
        return { id: nextId(), type: 'tool_start', content: summary, timestamp: Date.now() }
      }

      case 'tool_end': {
        const endTool = (event.tool as string) || ''
        if (endTool === 'finish_task' || endTool === 'give_up_on_task') return null
        const result = (event.result as string) || ''
        const truncated = result.length > 300 ? result.slice(0, 300) + '...' : result
        return { id: nextId(), type: 'tool_end', content: truncated, timestamp: Date.now(), meta: { tool: event.tool, stop: event.stop } }
      }

      case 'error':
        return { id: nextId(), type: 'error', content: event.message as string, timestamp: Date.now() }

      case 'stalled':
      case 'reacted':
        return null

      case 'agent_end':
        return null

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
        // Sync processing state with whether the agent is still running
        setIsProcessing(lastType !== 'agent_end')
        return
      }

      if (type === 'agent_end') setIsProcessing(false)
      const msg = eventToMessage(event)
      if (msg) {
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

  // Reset textarea height when input is cleared
  useEffect(() => {
    if (!input && inputRef.current) {
      inputRef.current.style.height = 'auto'
    }
  }, [input])

  // Auto-scroll to bottom
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  const handleSubmit = useCallback(() => {
    const trimmed = input.trim()
    if (!trimmed || isProcessing || status !== 'connected') return

    // Save to prompt history (dedup, cap at 100, persist)
    const idx = promptHistory.indexOf(trimmed)
    if (idx !== -1) promptHistory.splice(idx, 1)
    promptHistory.unshift(trimmed)
    if (promptHistory.length > 100) promptHistory.length = 100
    localStorage.setItem('prompt-history', JSON.stringify(promptHistory))
    historyIndexRef.current = -1

    addMessage(setMessages, 'user', trimmed)

    if (trimmed === '/help') {
      addMessage(setMessages, 'help', welcomeLines.join('\n'))
      setInput('')
      return
    }

    if (trimmed === '/clear') {
      sessionIdRef.current = null
      setMessages([])
      setIsProcessing(false)
      setInput('')
      fetch('/api/chat-history', { method: 'DELETE' }).catch(() => {})
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

    if (trimmed.startsWith('/load-pdf')) {
      const pdfPath = trimmed.slice(9).trim()
      if (!pdfPath) {
        addMessage(setMessages, 'status', 'Usage: /load-pdf <path>')
        setInput('')
        return
      }
      fetch('/api/load-pdf', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path: pdfPath }),
      })
        .then(r => r.json())
        .then(data => {
          if (data.error) addMessage(setMessages, 'error', data.error)
          else addMessage(setMessages, 'status', `Loaded: ${data.path}`)
        })
        .catch(() => addMessage(setMessages, 'error', 'Failed to load PDF.'))
      setInput('')
      return
    }

    if (trimmed === '/reset-pdf') {
      fetch('/api/reset-pdf', { method: 'POST' })
        .then(() => addMessage(setMessages, 'status', 'PDF viewer reset to built paper.'))
        .catch(() => addMessage(setMessages, 'error', 'Failed to reset PDF.'))
      setInput('')
      return
    }

    send(JSON.stringify({ content: trimmed }))
    setInput('')
    setIsProcessing(true)
  }, [input, isProcessing, status, send, welcomeLines, messages, reconnect])

  const handleCancel = useCallback(() => {
    if (!isProcessing || status !== 'connected') return
    send(JSON.stringify({ type: 'cancel' }))
    addMessage(setMessages, 'status', 'Cancelling...')
  }, [isProcessing, status, send])

  // Global Escape to cancel — textarea is disabled during processing
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isProcessing) handleCancel()
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [isProcessing, handleCancel])

  // Command autocomplete (merge backend capabilities + client commands)
  const allCommands = useMemo(() => [
    ...commands,
    ...CLIENT_COMMANDS.map(c => ({ ...c, arg_label: '', args: '' })),
  ].sort((a, b) => a.name.localeCompare(b.name)), [commands])
  const filteredCommands = input.startsWith('/')
    ? allCommands.filter(c => c.name.startsWith(input.split(' ')[0]))
    : []
  const showCmdDropdown = filteredCommands.length > 0 && !input.includes(' ')

  const selectCommand = useCallback((cmd: CommandDef) => {
    // Use just the command word (strip arg hints like "[N]" or "<path>")
    setInput(cmd.name.split(' ')[0] + ' ')
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
    if (e.key === 'ArrowUp' && !showCmdDropdown && promptHistory.length > 0) {
      const el = inputRef.current
      // Only navigate history if cursor is on the first line
      if (el && el.selectionStart !== undefined && el.value.slice(0, el.selectionStart).indexOf('\n') === -1) {
        e.preventDefault()
        const next = Math.min(historyIndexRef.current + 1, promptHistory.length - 1)
        historyIndexRef.current = next
        setInput(promptHistory[next])
        requestAnimationFrame(() => { if (el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px' } })
      }
    }
    if (e.key === 'ArrowDown' && !showCmdDropdown && historyIndexRef.current >= 0) {
      e.preventDefault()
      const el = inputRef.current
      const next = historyIndexRef.current - 1
      historyIndexRef.current = next
      setInput(next >= 0 ? promptHistory[next] : '')
      requestAnimationFrame(() => { if (el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 'px' } })
    }
    if (e.key === 'Escape' && isProcessing) {
      handleCancel()
    }
  }, [handleSubmit, isProcessing, handleCancel, showCmdDropdown, filteredCommands, cmdHighlight, selectCommand, promptHistory])

  const [isDragging, setIsDragging] = useState(false)

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const file = e.dataTransfer.files[0]
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
      addMessage(setMessages, 'error', 'Only PDF files are supported.')
      return
    }
    addMessage(setMessages, 'status', `Uploading ${file.name}...`)
    const form = new FormData()
    form.append('file', file)
    fetch('/api/upload-pdf', { method: 'POST', body: form })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          addMessage(setMessages, 'error', data.error)
          return
        }
        addMessage(setMessages, 'status', `Loaded ${data.filename} into viewer.`)
        // Send extracted text to the agent as context
        if (data.text_ok && data.text && status === 'connected' && !isProcessing) {
          const maxChars = 50000
          const text = data.text.length > maxChars
            ? data.text.slice(0, maxChars) + '\n\n[...truncated — full text available via read_pdf tool]'
            : data.text
          const prompt = `I've loaded a PDF: "${data.filename}". Here is the extracted text:\n\n${text}`
          send(JSON.stringify({ content: prompt }))
          setIsProcessing(true)
        }
      })
      .catch(() => addMessage(setMessages, 'error', 'Failed to upload PDF.'))
  }, [status, isProcessing, send])

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
    <div
      style={styles.container}
      onClick={() => inputRef.current?.focus()}
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
    >
      {/* Header */}
      <div style={styles.header}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
          <span style={styles.headerTitle}>AGENTIC L<span style={{ fontSize: '11px' }}>A</span>T<span style={{ fontSize: '11px' }}>E</span>X{appVersion && <span style={{ color: '#fff', fontSize: '10px', fontWeight: 400 }}> v{appVersion}</span>}</span>
          {headerExtra && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginRight: '8px' }}>
              {headerExtra}
            </div>
          )}
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

      {/* Drop overlay */}
      {isDragging && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 90,
          background: 'rgba(79, 195, 247, 0.1)',
          border: '2px dashed #4fc3f7',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          pointerEvents: 'none',
        }}>
          <span style={{ color: '#4fc3f7', fontSize: '14px', fontFamily: 'var(--font-mono)' }}>
            Drop PDF to load
          </span>
        </div>
      )}

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
            <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '16px', color: 'var(--al-brand)' }}>
              Change Model
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
                background: 'var(--al-brand)', border: 'none',
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
            {welcomeLines.map((line, i) => {
              const isHeader = line === welcomeLines[0] || line.startsWith('NATURAL LANGUAGE')
              const cmdMatch = line.match(/^(\s*)(\/\S+)(.*)/)
              const nlMatch = line.match(/^(\s*)("[^"]+")(.*)/);
              return (
                <span key={i}>
                  {i > 0 && '\n'}
                  {isHeader ? <span style={{ color: 'var(--al-interactive)' }}>{line}</span>
                    : cmdMatch ? <>{cmdMatch[1]}<span style={{ color: '#fff' }}>{cmdMatch[2]}</span>{cmdMatch[3]}</>
                    : nlMatch ? <>{nlMatch[1]}<span style={{ color: '#fff' }}>{nlMatch[2]}</span>{nlMatch[3]}</>
                    : line}
                </span>
              )
            })}
          </pre>
        )}
        {messages.map((msg) => (
          <div key={msg.id} style={styles.message(msg.type)}>
            {msg.type === 'user' && (
              <div style={{
                background: 'var(--dn-surface, #1a1a1a)',
                border: '1px solid var(--dn-border-lt, #2a2a2a)',
                borderRadius: '6px',
                padding: '8px 12px',
                display: 'inline-block',
                maxWidth: '90%',
              }}>
                <span style={styles.prompt}>&gt;</span>
                {msg.content}
              </div>
            )}
            {msg.type === 'assistant' && (
              <div className="markdown-body" style={{ fontFamily: 'inherit', fontSize: '13px', lineHeight: '1.5' }}>
                <Markdown remarkPlugins={[remarkGfm]}>{msg.content}</Markdown>
              </div>
            )}
            {msg.type === 'tool_start' && (
              <>
                <span style={styles.toolBadge}>TOOL</span>
                <span style={{ color: 'var(--dn-text-muted)', fontSize: '12px' }}>{msg.content}</span>
              </>
            )}
            {msg.type === 'tool_end' && msg.content && (
              <pre style={{
                margin: '0 0 0 12px',
                whiteSpace: 'pre-wrap',
                fontFamily: 'inherit',
                fontSize: '11px',
                color: 'var(--dn-text-muted)',
                maxHeight: '120px',
                overflow: 'auto',
              }}>
                {msg.content}
              </pre>
            )}
            {msg.type === 'help' && (
              <pre style={{ margin: 0, fontFamily: 'inherit', fontSize: '12px', lineHeight: '1.6', color: 'var(--dn-text-dim)', whiteSpace: 'pre' }}>
                {msg.content.split('\n').map((line, i) => {
                  const isHeader = i === 0 || line.startsWith('NATURAL LANGUAGE')
                  const cmdMatch = line.match(/^(\s*)(\/\S+)(.*)/)
                  const nlMatch = line.match(/^(\s*)("[^"]+")(.*)/);
                  return (
                    <span key={i}>
                      {i > 0 && '\n'}
                      {isHeader ? <span style={{ color: 'var(--al-interactive)' }}>{line}</span>
                        : cmdMatch ? <>{cmdMatch[1]}<span style={{ color: '#fff' }}>{cmdMatch[2]}</span>{cmdMatch[3]}</>
                        : nlMatch ? <>{nlMatch[1]}<span style={{ color: '#fff' }}>{nlMatch[2]}</span>{nlMatch[3]}</>
                        : line}
                    </span>
                  )
                })}
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
                <span style={{ color: 'var(--al-interactive)', minWidth: '180px' }}>{cmd.name}</span>
                <span style={{ color: '#fff', fontSize: '11px' }}>{cmd.description}</span>
              </div>
            ))}
          </div>
        )}
      <div style={styles.inputArea}>
        <span style={styles.prompt}>&gt;</span>
        {!isProcessing && status === 'connected' && input === '' && (
          <span style={styles.cursor} />
        )}
        <textarea
          ref={inputRef}
          style={styles.input}
          value={input}
          rows={1}
          onChange={(e) => {
            setInput(e.target.value)
            setCmdHighlight(0)
            e.target.style.height = 'auto'
            e.target.style.height = e.target.scrollHeight + 'px'
          }}
          onKeyDown={handleKeyDown}
          placeholder={status !== 'connected' ? 'Connecting...' : ''}
          disabled={status !== 'connected' || isProcessing}
        />
        {isProcessing && (
          <span className="agent-working" style={{
            position: 'absolute', left: '28px', top: '50%', transform: 'translateY(-50%)',
            color: 'var(--al-interactive)', fontSize: '13px', fontFamily: 'var(--font-mono)',
            pointerEvents: 'none', opacity: 0.6,
          }}>Agent working</span>
        )}
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
