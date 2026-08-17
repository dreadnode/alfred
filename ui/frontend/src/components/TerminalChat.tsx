import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import Markdown from 'react-markdown'
import rehypeKatex from 'rehype-katex'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import 'katex/dist/katex.min.css'
import { agentVerb } from '../agentVerbs'
import { loadArtifactContent } from '../artifactContent'
import type { ConnectionStatus } from '../hooks/useWebSocket'
import {
  IMAGE_FILE_ACCEPT,
  type ImageAttachment,
  planImageSelection,
  readFileAsBase64,
  resolveImageMediaType,
} from '../imageAttachments'

// --- Types ---

interface ChatMessage {
  id: string
  type: 'user' | 'assistant' | 'tool_start' | 'tool_end' | 'status' | 'error' | 'help' | 'file_artifact'
  content: string
  timestamp: number
  meta?: Record<string, unknown>
}

interface ChatEvent {
  type: string
  [key: string]: unknown
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

// --- Helpers ---

let msgId = 0
function nextId(): string {
  return `msg-${++msgId}`
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) { const v = n / 1_000_000; return (v >= 10 ? Math.round(v) : +v.toFixed(1)) + 'M' }
  if (n >= 1_000) { const v = n / 1_000; return (v >= 10 ? Math.round(v) : +v.toFixed(1)) + 'k' }
  return String(n)
}

const CLIENT_COMMANDS = [
  { name: '/clear', description: 'Reset session and start fresh' },
  { name: '/copy [N|all]', description: 'Copy last N agent messages (default 1, "all" for entire chat)' },
  { name: '/help', description: 'Show this guide' },
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

const CATEGORY_ORDER = ['research', 'review', 'writing', 'session'] as const

const CATEGORY_LABELS: Record<string, string> = {
  research: 'Research',
  review: 'Review',
  writing: 'Writing',
  session: 'Session',
}

interface CommandDef {
  name: string
  description: string
  arg_label: string
  args: string
  category?: string
}

function buildWelcomeLines(commands: CommandDef[]): string[] {
  const cmdEntries = commands.map(c => {
    let usage = c.name
    if (c.arg_label) {
      const isOptional = c.args === 'optional'
      usage += isOptional ? ` [${c.arg_label}]` : ` <${c.arg_label}>`
    }
    return { usage, desc: c.description, category: c.category || 'session' }
  })

  CLIENT_COMMANDS.forEach(c => cmdEntries.push({ usage: c.name, desc: c.description, category: 'session' }))

  const maxUsage = Math.max(...cmdEntries.map(c => c.usage.length))
  const col = maxUsage + 3

  const grouped: Record<string, typeof cmdEntries> = {}
  for (const entry of cmdEntries) {
    (grouped[entry.category] ??= []).push(entry)
  }

  const lines: string[] = [
    'COMMANDS                              type / to see all',
  ]

  for (const cat of CATEGORY_ORDER) {
    const entries = grouped[cat]
    if (!entries?.length) continue
    lines.push('', `  ${CATEGORY_LABELS[cat] || cat}`)
    for (const c of entries) {
      lines.push(`    ${c.usage.padEnd(col)}${c.desc}`)
    }
  }

  lines.push(
    '',
    'NATURAL LANGUAGE',
    '',
    ...NATURAL_LANGUAGE_LINES.map(l => `  ${l}`),
    '',
    '  Or just ask — edit sections, add figures, fix errors, etc.',
  )
  return lines
}

function eventToMessage(event: ChatEvent, id: string): ChatMessage | null {
  const type = event.type as string

  switch (type) {
    case 'user_message':
      return {
        id, type: 'user', content: event.content as string, timestamp: 0,
        meta: event.images || event.image_count
          ? { images: event.images, image_count: event.image_count }
          : undefined,
      }

    case 'agent_start':
    case 'step_start':
      return null

    case 'generation':
      if (event.content) {
        return { id, type: 'assistant', content: event.content as string, timestamp: 0, meta: event.usage as Record<string, unknown> | undefined }
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
          add_citation: a => `Adding citation: ${a.citation_id || '?'}`,
          paper_stats: () => 'Getting paper stats...',
          generate_diff: a => `Generating diff${a.revision ? ` vs ${a.revision}` : ''}...`,
          switch_template: a => `Switching template to ${a.template_name || '?'}...`,
          list_templates: () => 'Listing templates...',
          list_reviews: () => 'Listing reviews...',
          emit_file_artifact: a => `Saving artifact: ${a.label || a.path || 'file'}`,
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
      return { id, type: 'tool_start', content: summary, timestamp: 0 }
    }

    case 'tool_end': {
      const endTool = (event.tool as string) || ''
      if (endTool === 'finish_task' || endTool === 'give_up_on_task') return null
      const result = (event.result as string) || ''
      const truncated = result.length > 300 ? result.slice(0, 300) + '...' : result
      return { id, type: 'tool_end', content: truncated, timestamp: 0, meta: { tool: event.tool, stop: event.stop } }
    }

    case 'error':
      return { id, type: 'error', content: event.message as string, timestamp: 0 }

    case 'status':
      return { id, type: 'status', content: event.content as string, timestamp: 0 }

    case 'file_artifact':
      return {
        id, type: 'file_artifact',
        content: (event.content as string) || '',
        timestamp: 0,
        meta: {
          artifact_id: event.artifact_id,
          filename: event.filename,
          label: event.label,
          path: event.path,
          size_bytes: event.size_bytes,
        },
      }

    case 'stalled':
    case 'reacted':
    case 'agent_end':
      return null

    default:
      return null
  }
}

// --- Component ---

interface TerminalChatProps {
  sessionId: string
  events: ChatEvent[]
  isProcessing: boolean
  wsStatus: ConnectionStatus
  onSend: (content: string, images?: ImageAttachment[]) => void
  onCancel: () => void
  onClear: () => void
  hasPaper: boolean
  onToggleView: () => void
}

export default function TerminalChat({
  sessionId,
  events,
  isProcessing,
  wsStatus,
  onSend,
  onCancel,
  onClear,
  hasPaper,
  onToggleView,
}: TerminalChatProps) {
  const [input, setInput] = useState('')
  const [localMessages, setLocalMessages] = useState<ChatMessage[]>([])
  const [promptHistory] = useState<string[]>(() => {
    try {
      const parsed = JSON.parse(localStorage.getItem('prompt-history') || '[]')
      return Array.isArray(parsed) ? parsed : []
    } catch { return [] }
  })
  const historyIndexRef = useRef(-1)

  const [verb, setVerb] = useState(() => agentVerb(0))
  useLayoutEffect(() => {
    if (isProcessing) setVerb(agentVerb(Date.now()))
  }, [isProcessing])

  const [modelName, setModelName] = useState('')
  const [showSettings, setShowSettings] = useState(false)
  const [settingsModel, setSettingsModel] = useState('')
  const [settingsApiKey, setSettingsApiKey] = useState('')
  const [settingsApiKeyEnv, setSettingsApiKeyEnv] = useState('')
  const [settingsError, setSettingsError] = useState('')
  const [settingsSaving, setSettingsSaving] = useState(false)
  const [pendingImages, setPendingImages] = useState<ImageAttachment[]>([])
  const pendingImagesRef = useRef<ImageAttachment[]>([])
  const imageSelectionQueueRef = useRef<Promise<void>>(Promise.resolve())
  const imageSelectionGenerationRef = useRef(0)
  const [imageError, setImageError] = useState('')
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [commands, setCommands] = useState<CommandDef[]>([])
  const [cmdHighlight, setCmdHighlight] = useState(0)
  const [fileBrowser, setFileBrowser] = useState<{
    dir: string
    entries: { name: string; path: string; is_dir: boolean }[]
    command: string
  } | null>(null)
  const welcomeLines = useMemo(() => buildWelcomeLines(commands), [commands])
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const initialScrollDone = useRef(false)

  const addImageFiles = useCallback((files: FileList | File[]): Promise<void> => {
    const selected = Array.from(files)
    const generation = imageSelectionGenerationRef.current
    const operation = imageSelectionQueueRef.current.then(async () => {
      const plan = planImageSelection(pendingImagesRef.current, selected)
      const attachments: ImageAttachment[] = []
      const errors = [...plan.errors]
      for (const { file, mediaType } of plan.accepted) {
        try {
          const data = await readFileAsBase64(file)
          attachments.push({
            data,
            media_type: mediaType,
            name: file.name,
            size: file.size,
          })
        } catch {
          errors.push(`${file.name || 'Attachment'} could not be read`)
        }
      }
      if (generation !== imageSelectionGenerationRef.current) return
      if (attachments.length > 0) {
        const next = [...pendingImagesRef.current, ...attachments]
        pendingImagesRef.current = next
        setPendingImages(next)
      }
      setImageError([...new Set(errors)].join('. '))
    })
    imageSelectionQueueRef.current = operation.catch(() => {})
    return operation
  }, [])

  const clearPendingImages = useCallback(() => {
    imageSelectionGenerationRef.current += 1
    pendingImagesRef.current = []
    setPendingImages([])
  }, [])

  const removePendingImage = useCallback((index: number) => {
    const next = pendingImagesRef.current.filter((_, candidate) => candidate !== index)
    pendingImagesRef.current = next
    setPendingImages(next)
  }, [])

  const copyArtifact = useCallback(async (message: ChatMessage) => {
    const status = document.getElementById(`artifact-${message.id}`)
    try {
      const artifactId = message.meta?.artifact_id
      if (typeof artifactId === 'string' && artifactId) {
        if (status) status.textContent = 'Loading...'
      }
      const content = await loadArtifactContent(sessionId, artifactId, message.content)
      await navigator.clipboard.writeText(content)
      if (status) {
        status.textContent = 'Copied!'
        setTimeout(() => { status.textContent = 'Click to copy' }, 1500)
      }
    } catch {
      if (status) {
        status.textContent = 'Copy failed'
        setTimeout(() => { status.textContent = 'Click to copy' }, 2000)
      }
    }
  }, [sessionId])

  // Fetch config and commands on mount
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => { setModelName(data.model || '') })
      .catch(() => {})
    fetch('/api/commands')
      .then(r => r.json())
      .then(data => setCommands(data))
      .catch(() => {})
  }, [])

  // Convert events to messages
  const messages = useMemo(() => {
    const result: ChatMessage[] = []
    for (const [index, event] of events.entries()) {
      const msg = eventToMessage(event, `event-${index}`)
      if (msg) result.push(msg)
    }
    // Merge local client-side messages (e.g. /help) into the timeline
    return [...result, ...localMessages]
  }, [events, localMessages])

  const sessionTokens = useMemo(() => {
    let input = 0
    let output = 0
    for (const event of events) {
      if (event.type !== 'generation') continue
      const usage = event.usage as Record<string, number> | undefined
      input += usage?.input_tokens || 0
      output += usage?.output_tokens || 0
    }
    return { input, output }
  }, [events])

  // Focus input when ready
  useEffect(() => {
    if (wsStatus === 'connected' && !isProcessing) {
      inputRef.current?.focus()
    }
  }, [wsStatus, isProcessing])

  // Reset textarea height when input is cleared
  useEffect(() => {
    if (!input && inputRef.current) {
      inputRef.current.style.height = 'auto'
    }
  }, [input])

  // Auto-scroll to bottom — instant on first render, smooth after
  useEffect(() => {
    const behavior = initialScrollDone.current ? 'smooth' : 'instant'
    messagesEndRef.current?.scrollIntoView({ behavior })
    initialScrollDone.current = true
  }, [messages])

  const handleSubmit = useCallback(() => {
    const trimmed = input.trim()
    const hasImages = pendingImages.length > 0
    if ((!trimmed && !hasImages) || isProcessing || wsStatus !== 'connected') return

    // Save to prompt history
    if (trimmed) {
      const idx = promptHistory.indexOf(trimmed)
      if (idx !== -1) promptHistory.splice(idx, 1)
      promptHistory.unshift(trimmed)
      if (promptHistory.length > 100) promptHistory.length = 100
      localStorage.setItem('prompt-history', JSON.stringify(promptHistory))
    }
    historyIndexRef.current = -1

    if (trimmed === '/help') {
      setLocalMessages(prev => [
        ...prev,
        { id: nextId(), type: 'user', content: '/help', timestamp: Date.now() },
        { id: nextId(), type: 'help', content: '', timestamp: Date.now() },
      ])
      setInput('')
      return
    }

    if (trimmed === '/clear') {
      onClear()
      setLocalMessages([])
      setInput('')
      clearPendingImages()
      return
    }

    if (trimmed.startsWith('/copy')) {
      const countArg = trimmed.slice(5).trim()
      const all = messages.filter(m => m.type === 'assistant')
      const copyAll = countArg.toLowerCase() === 'all'
      const parsed = countArg && !copyAll ? parseInt(countArg, 10) : 1
      const count = isNaN(parsed) || parsed <= 0 ? 1 : parsed
      const selected = copyAll ? all : all.slice(-count)
      const text = selected.map(m => m.content).join('\n\n')
      if (selected.length === 0) {
        setInput('')
        return
      }
      navigator.clipboard.writeText(text).catch(() => {})
      setInput('')
      return
    }

    if (trimmed === '/process-peer-review') {
      fetch(`/api/files?dir=~`)
        .then(r => r.json())
        .then(data => {
          if (data.entries) {
            setFileBrowser({ dir: data.dir, entries: data.entries, command: trimmed })
          } else {
            onSend(trimmed)
          }
        })
        .catch(() => onSend(trimmed))
      setInput('')
      return
    }

    const content = trimmed || (hasImages ? 'Convert this image to LaTeX' : '')
    onSend(content, hasImages ? pendingImages : undefined)
    setInput('')
    clearPendingImages()
    setImageError('')
  }, [input, isProcessing, wsStatus, onSend, onClear, messages, sessionId, promptHistory, pendingImages, clearPendingImages])

  const browseDir = useCallback((dir: string) => {
    fetch(`/api/files?dir=${encodeURIComponent(dir)}`)
      .then(r => r.json())
      .then(data => {
        if (data.entries) {
          setFileBrowser(prev => prev ? { ...prev, dir: data.dir, entries: data.entries } : null)
        }
      })
      .catch(() => {})
  }, [])

  const handleCancel = useCallback(() => {
    if (!isProcessing || wsStatus !== 'connected') return
    onCancel()
  }, [isProcessing, wsStatus, onCancel])

  // Global Escape to cancel
  useEffect(() => {
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && isProcessing) handleCancel()
    }
    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [isProcessing, handleCancel])

  // Command autocomplete
  const allCommands = useMemo(() => [
    ...commands,
    ...CLIENT_COMMANDS.map(c => ({ ...c, arg_label: '', args: '' })),
  ].sort((a, b) => a.name.localeCompare(b.name)), [commands])
  const filteredCommands = input.startsWith('/')
    ? allCommands.filter(c => c.name.startsWith(input.split(' ')[0]))
    : []
  const showCmdDropdown = filteredCommands.length > 0 && !input.includes(' ')

  const selectCommand = useCallback((cmd: CommandDef) => {
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
    const files = Array.from(e.dataTransfer.files)
    if (files.length === 0) return

    const pdf = files.find(file => file.name.toLowerCase().endsWith('.pdf'))
    if (pdf) {
      const form = new FormData()
      form.append('file', pdf)
      fetch(`/api/sessions/${sessionId}/upload-pdf`, { method: 'POST', body: form })
        .then(r => r.json())
        .then(data => {
          if (data.text_ok && data.text && wsStatus === 'connected' && !isProcessing) {
            const maxChars = 50000
            const text = data.text.length > maxChars
              ? data.text.slice(0, maxChars) + '\n\n[...truncated — full text available via read_pdf tool]'
              : data.text
            const prompt = `I've loaded a PDF: "${data.filename}". Here is the extracted text:\n\n${text}`
            onSend(prompt)
          }
        })
        .catch(() => {})
      return
    }

    void addImageFiles(files)
  }, [sessionId, wsStatus, isProcessing, onSend, addImageFiles])

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
      const configRes = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, api_key: key, api_key_env: env }),
      })
      const config = await configRes.json()
      if (config.error) { setSettingsError(config.error); return }

      const effectiveModel = config.model || model
      const sessionRes = await fetch(`/api/sessions/${sessionId}/model`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: effectiveModel }),
      })
      const session = await sessionRes.json()
      if (session.error) { setSettingsError(session.error); return }

      setModelName(effectiveModel)
      setShowSettings(false)
    } catch (e) {
      setSettingsError(`Failed to save: ${e}`)
    } finally {
      setSettingsSaving(false)
    }
  }, [settingsModel, settingsApiKey, settingsApiKeyEnv, sessionId])


  return (
    <div
      style={styles.container}
      onClick={() => inputRef.current?.focus()}
      onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
    >
      {/* Header */}
      <div style={styles.header} onClick={e => e.stopPropagation()}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
          {hasPaper && (
            <span style={{
              display: 'inline-flex', border: '1px solid var(--dn-border)', borderRadius: '3px',
              fontFamily: 'var(--font-mono)', fontSize: '11px', userSelect: 'none', overflow: 'hidden',
            }}>
              <span style={{
                padding: '2px 8px', background: 'var(--al-brand)', color: 'var(--dn-black)', fontWeight: 600,
              }}>Agent</span>
              <span
                role="button" tabIndex={0}
                onClick={onToggleView}
                onKeyDown={e => { if (e.key === 'Enter') onToggleView() }}
                style={{ padding: '2px 8px', cursor: 'pointer', color: 'var(--dn-text-dim)', background: 'transparent' }}
                title="Switch to notepad"
              >Notepad</span>
            </span>
          )}
          {modelName && (
            <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={styles.statusDot(wsStatus)} />
              <span
                role="button" tabIndex={0}
                onClick={openSettings}
                onKeyDown={e => { if (e.key === 'Enter') openSettings() }}
                style={{ color: '#4fc3f7', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline', textDecorationStyle: 'dotted' as const, textUnderlineOffset: '3px' }}
                title="Change model settings"
              >{modelName}</span>
              {(sessionTokens.input > 0 || sessionTokens.output > 0) && (
                <span
                  style={{ color: 'var(--dn-warning, #e5c07b)', fontSize: '10px', whiteSpace: 'nowrap' }}
                  title={`Input: ${sessionTokens.input.toLocaleString()} tokens\nOutput: ${sessionTokens.output.toLocaleString()} tokens`}
                ><span style={{ color: 'var(--dn-text-bright, #fff)' }}>↑</span>{formatTokens(sessionTokens.input)} <span style={{ color: 'var(--dn-text-bright, #fff)' }}>↓</span>{formatTokens(sessionTokens.output)}</span>
              )}
            </span>
          )}
        </div>
        <div />
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
            Drop PDF or image
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

      {/* File browser modal */}
      {fileBrowser && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 100,
          background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setFileBrowser(null)}>
          <div style={{
            background: 'var(--dn-bg-lt, #1e1e1e)', border: '1px solid var(--dn-border-lt, #444)',
            borderRadius: '6px', padding: '20px', width: '500px', maxHeight: '70vh',
            fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--dn-text, #ccc)',
            display: 'flex', flexDirection: 'column',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '12px', color: 'var(--al-brand)' }}>
              Select File
            </div>
            {/* Current path + back button */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px',
              padding: '6px 8px', background: 'var(--dn-bg, #121212)', borderRadius: '3px',
              border: '1px solid var(--dn-border, #333)',
            }}>
              <span
                role="button" tabIndex={0}
                onClick={() => {
                  const parent = fileBrowser.dir.replace(/\/[^/]+\/?$/, '') || '/'
                  if (parent !== fileBrowser.dir) browseDir(parent)
                }}
                onKeyDown={e => {
                  if (e.key === 'Enter') {
                    const parent = fileBrowser.dir.replace(/\/[^/]+\/?$/, '') || '/'
                    if (parent !== fileBrowser.dir) browseDir(parent)
                  }
                }}
                style={{ cursor: 'pointer', fontSize: '14px', flexShrink: 0 }}
                title="Go up"
              >⬆</span>
              <span style={{ color: 'var(--dn-text-dim)', fontSize: '11px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', direction: 'rtl', textAlign: 'left' }}>
                {fileBrowser.dir}
              </span>
            </div>
            {/* File listing */}
            <div style={{ overflowY: 'auto', flex: 1, minHeight: 0 }}>
              {fileBrowser.entries.length === 0 && (
                <div style={{ color: 'var(--dn-text-dim)', padding: '16px', textAlign: 'center' }}>Empty directory</div>
              )}
              {fileBrowser.entries.map(entry => (
                <div
                  key={entry.path}
                  role="button" tabIndex={0}
                  onClick={() => {
                    if (entry.is_dir) {
                      browseDir(entry.path)
                    } else {
                      onSend(`${fileBrowser.command} ${entry.path}`)
                      setFileBrowser(null)
                    }
                  }}
                  onKeyDown={e => {
                    if (e.key === 'Enter') {
                      if (entry.is_dir) {
                        browseDir(entry.path)
                      } else {
                        onSend(`${fileBrowser.command} ${entry.path}`)
                        setFileBrowser(null)
                      }
                    }
                  }}
                  style={{
                    display: 'flex', alignItems: 'center', gap: '8px',
                    padding: '6px 8px',
                    cursor: 'pointer',
                    borderRadius: '3px',
                    marginBottom: '2px',
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={e => (e.currentTarget.style.background = 'var(--dn-surface, #1a1a1a)')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                >
                  <span style={{ fontSize: '14px', flexShrink: 0 }}>{entry.is_dir ? '📁' : '📄'}</span>
                  <span style={{ color: entry.is_dir ? 'var(--al-brand)' : 'var(--dn-text-bright, #fff)', fontSize: '12px' }}>
                    {entry.name}
                  </span>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '12px' }}>
              <button onClick={() => setFileBrowser(null)} style={{
                background: 'transparent', border: '1px solid var(--dn-border-lt, #444)',
                color: 'var(--dn-text-dim, #888)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                padding: '4px 12px', borderRadius: '3px', cursor: 'pointer',
              }}>CANCEL</button>
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
                {Array.isArray(msg.meta?.images) && (msg.meta.images as { data: string; media_type: string }[]).length > 0 && (
                  <div style={{ display: 'flex', gap: '6px', marginBottom: '6px', flexWrap: 'wrap' }}>
                    {(msg.meta.images as { data: string; media_type: string }[]).map((img, i) => (
                      <img
                        key={i}
                        src={`data:${img.media_type};base64,${img.data}`}
                        alt="attached"
                        style={{
                          height: '60px', maxWidth: '120px', objectFit: 'cover',
                          borderRadius: '4px', border: '1px solid var(--dn-border)',
                        }}
                      />
                    ))}
                  </div>
                )}
                {!Array.isArray(msg.meta?.images) && typeof msg.meta?.image_count === 'number' && msg.meta.image_count > 0 && (
                  <div style={{ color: 'var(--dn-text-dim)', fontSize: '11px', marginBottom: '6px' }}>
                    [{msg.meta.image_count} image attachment{msg.meta.image_count === 1 ? '' : 's'}]
                  </div>
                )}
                <span style={styles.prompt}>&gt;</span>
                {msg.content}
              </div>
            )}
            {msg.type === 'assistant' && (
              <div className="markdown-body" style={{ fontFamily: 'inherit', fontSize: '13px', lineHeight: '1.5' }}>
                <Markdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>{
                  msg.content.replace(/```[\s\S]*?```|`[^`]+`|\\\[([\s\S]*?)\\\]|\\\((.*?)\\\)/g,
                    (m, display, inline) => display !== undefined ? `$$${display}$$` : inline !== undefined ? `$${inline}$` : m)
                }</Markdown>
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
            {msg.type === 'status' && (
              <span style={{ fontStyle: 'italic' }}>{msg.content}</span>
            )}
            {msg.type === 'help' && (
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
            {msg.type === 'file_artifact' && (
              <div
                role="button" tabIndex={0}
                onClick={() => { void copyArtifact(msg) }}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    void copyArtifact(msg)
                  }
                }}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: '10px',
                  padding: '10px 16px',
                  background: 'var(--dn-surface, #1a1a1a)',
                  border: '1px solid var(--dn-border-lt, #2a2a2a)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  transition: 'border-color 0.15s',
                  maxWidth: '90%',
                }}
                onMouseEnter={e => (e.currentTarget.style.borderColor = 'var(--al-brand)')}
                onMouseLeave={e => (e.currentTarget.style.borderColor = 'var(--dn-border-lt, #2a2a2a)')}
                title="Click to copy file contents to clipboard"
              >
                <span style={{ fontSize: '20px' }}>📄</span>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '2px' }}>
                  <span style={{ color: 'var(--dn-text-bright, #fff)', fontSize: '12px', fontWeight: 600 }}>
                    {(msg.meta?.label as string) || (msg.meta?.filename as string) || 'File'}
                  </span>
                  <span style={{ color: 'var(--dn-text-dim)', fontSize: '10px' }}>
                    {(msg.meta?.path as string) || (msg.meta?.filename as string) || ''}
                  </span>
                  <span id={`artifact-${msg.id}`} style={{ color: 'var(--al-brand)', fontSize: '10px' }}>
                    Click to copy
                  </span>
                </div>
              </div>
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
        {isProcessing && (
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px', marginBottom: '8px' }}>
            <span className="agent-working" style={{
              fontSize: '13px', fontFamily: 'var(--font-mono)',
            }}>Agent {verb}</span>
            <span role="button" tabIndex={0} style={{
              color: 'var(--dn-text-dim)', fontSize: '12px', fontFamily: 'var(--font-mono)',
              cursor: 'pointer',
            }} onClick={handleCancel} onKeyDown={e => { if (e.key === 'Enter') handleCancel() }}>Press Esc to cancel</span>
          </div>
        )}
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
      {/* Image preview strip */}
      {pendingImages.length > 0 && (
        <div style={{
          display: 'flex', gap: '8px', padding: '8px 16px',
          borderTop: '1px solid var(--dn-border)',
          background: 'var(--dn-black)',
          flexWrap: 'wrap',
        }}>
          {pendingImages.map((img, i) => (
            <div key={i} style={{ position: 'relative', display: 'inline-block' }}>
              <img
                src={`data:${img.media_type};base64,${img.data}`}
                alt={img.name}
                style={{
                  height: '48px', maxWidth: '80px', objectFit: 'cover',
                  borderRadius: '4px', border: '1px solid var(--dn-border)',
                }}
              />
              <span
                role="button" tabIndex={0}
                onClick={() => removePendingImage(i)}
                onKeyDown={e => { if (e.key === 'Enter') removePendingImage(i) }}
                style={{
                  position: 'absolute', top: '-4px', right: '-4px',
                  width: '16px', height: '16px', borderRadius: '50%',
                  background: 'var(--dn-error)', color: '#fff',
                  fontSize: '10px', lineHeight: '16px', textAlign: 'center',
                  cursor: 'pointer',
                }}
              >x</span>
            </div>
          ))}
        </div>
      )}
      {imageError && (
        <div style={{
          padding: '4px 16px', fontSize: '11px', color: 'var(--dn-error)',
          fontFamily: 'var(--font-mono)', background: 'var(--dn-black)',
        }}>{imageError}</div>
      )}
      <div style={styles.inputArea}>
        <input
          ref={fileInputRef}
          type="file"
          accept={IMAGE_FILE_ACCEPT}
          multiple
          style={{ display: 'none' }}
          onChange={(e) => {
            if (e.target.files) void addImageFiles(e.target.files)
            e.target.value = ''
          }}
        />
        <span
          role="button" tabIndex={0}
          onClick={() => fileInputRef.current?.click()}
          onKeyDown={e => { if (e.key === 'Enter') fileInputRef.current?.click() }}
          style={{
            color: 'var(--dn-text-dim)', fontSize: '16px', cursor: 'pointer',
            marginRight: '8px', lineHeight: '1.5', userSelect: 'none',
          }}
          title="Attach image"
        >+</span>
        <span style={styles.prompt}>&gt;</span>
        {!isProcessing && wsStatus === 'connected' && input === '' && pendingImages.length === 0 && (
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
          onPaste={(e) => {
            const items = e.clipboardData?.items
            if (!items) return
            const imageFiles: File[] = []
            for (const item of Array.from(items)) {
              const file = item.kind === 'file' ? item.getAsFile() : null
              if (file && resolveImageMediaType(file)) imageFiles.push(file)
            }
            if (imageFiles.length > 0) {
              e.preventDefault()
              void addImageFiles(imageFiles)
            }
          }}
          placeholder={wsStatus !== 'connected' ? 'Connecting...' : ''}
          disabled={wsStatus !== 'connected'}
        />
      </div>
      </div>

    </div>
  )
}
