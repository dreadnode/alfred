import { useCallback, useEffect, useRef, useState } from 'react'
import TerminalChat from './components/TerminalChat'
import Notepad from './components/Notepad'
import PdfViewer from './components/PdfViewer'
import { useWebSocket } from './hooks/useWebSocket'
import {
  applyRoutedChatEvent,
  routeChatEvent,
  type ChatEvent,
} from './eventHistory'

const MIN_CHAT_WIDTH = 300
const MIN_PDF_WIDTH = 300
const DEFAULT_CHAT_RATIO = 0.5

interface Session {
  id: string
  label: string
  paper_dir: string | null
  model: string | null
  created_at: string
}

export default function App() {
  const [chatRatio, setChatRatio] = useState(DEFAULT_CHAT_RATIO)
  const dragging = useRef(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const resizerRef = useRef<HTMLDivElement>(null)

  // Session state
  const [sessions, setSessions] = useState<Session[]>([])
  const sessionsRef = useRef(sessions)
  sessionsRef.current = sessions
  const [activeId, setActiveId] = useState<string | null>(null)
  const [msgs, setMsgs] = useState<Record<string, ChatEvent[]>>({})
  const [processing, setProcessing] = useState<Record<string, boolean>>({})
  const resumedSessionIds = useRef(new Set<string>())

  // Left-pane view per session: 'chat' (default) or 'notepad'
  const [leftView, setLeftView] = useState<Record<string, 'chat' | 'notepad'>>({})

  // App info
  const [appVersion, setAppVersion] = useState('')

  // New session modal
  const [showNewSession, setShowNewSession] = useState(false)
  const [newLabel, setNewLabel] = useState('')

  // Fetch config on mount
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => setAppVersion(data.version || ''))
      .catch(() => {})
  }, [])

  // Fetch sessions on mount
  const fetchSessions = useCallback(async () => {
    try {
      const res = await fetch('/api/sessions')
      const data = await res.json()
      const list: Session[] = data.sessions || []
      setSessions(list)
      if (list.length > 0) {
        setActiveId(prev => prev ?? list[0].id)
      }
    } catch { /* ignore */ }
  }, [])

  useEffect(() => { fetchSessions() }, [fetchSessions])

  // WebSocket message handler — routes by session_id
  const handleWsMessage = useCallback((data: string) => {
    const routed = routeChatEvent(data)
    if (!routed) return

    setMsgs(prev => ({
      ...prev,
      [routed.sessionId]: applyRoutedChatEvent(
        prev[routed.sessionId] || [],
        routed,
      ),
    }))
    // Don't infer active processing from replayed history. Live send state is
    // authoritative, while agent_end explicitly returns a session to idle.
    if (routed.markIdle) {
      setProcessing(prev => ({ ...prev, [routed.sessionId]: false }))
    }
    if (routed.refreshSessions) fetchSessions()
  }, [])

  // On WS open, resume all sessions
  const handleWsOpen = useCallback((sendFn: (data: string) => void) => {
    resumedSessionIds.current.clear()
    sessionsRef.current.forEach(s => {
      sendFn(JSON.stringify({ session_id: s.id, type: 'resume' }))
      resumedSessionIds.current.add(s.id)
    })
  }, [])

  const { status, send } = useWebSocket('/ws/chat', handleWsMessage, handleWsOpen)

  // Resume sessions when they change (e.g., after creating a new one)
  const resumeSession = useCallback((sessionId: string) => {
    if (status === 'connected') {
      send(JSON.stringify({ session_id: sessionId, type: 'resume' }))
      resumedSessionIds.current.add(sessionId)
    }
  }, [status, send])

  // The WebSocket can connect before the initial session request finishes.
  // Resume any sessions that arrived after onopen so their history is loaded.
  useEffect(() => {
    if (status !== 'connected') return
    sessions.forEach(session => {
      if (!resumedSessionIds.current.has(session.id)) {
        send(JSON.stringify({ session_id: session.id, type: 'resume' }))
        resumedSessionIds.current.add(session.id)
      }
    })
  }, [sessions, status, send])

  // Send a message for the active session
  const sendMessage = useCallback((content: string, images?: { data: string; media_type: string; name: string }[]) => {
    if (!activeId || status !== 'connected') return
    const payload: Record<string, unknown> = { session_id: activeId, content }
    if (images && images.length > 0) {
      payload.images = images.map(({ data, media_type }) => ({ data, media_type }))
    }
    send(JSON.stringify(payload))
    setProcessing(prev => ({ ...prev, [activeId]: true }))
  }, [activeId, status, send])

  // Cancel active session
  const cancelActive = useCallback(() => {
    if (!activeId || status !== 'connected') return
    send(JSON.stringify({ session_id: activeId, type: 'cancel' }))
  }, [activeId, status, send])

  // Create a new session
  const createSession = useCallback(async (label?: string) => {
    try {
      const res = await fetch('/api/sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ label: label || undefined }),
      })
      const data = await res.json()
      if (data.error) return
      const newSession: Session = data
      setSessions(prev => [...prev, newSession])
      setActiveId(newSession.id)
      setMsgs(prev => ({ ...prev, [newSession.id]: [] }))
      resumeSession(newSession.id)
    } catch { /* ignore */ }
  }, [resumeSession])

  // Delete a session
  const deleteSession = useCallback(async (sessionId: string) => {
    try {
      await fetch(`/api/sessions/${sessionId}`, { method: 'DELETE' })
      setSessions(prev => {
        const next = prev.filter(s => s.id !== sessionId)
        if (activeId === sessionId) {
          setActiveId(next.length > 0 ? next[0].id : null)
        }
        return next
      })
      setMsgs(prev => {
        const next = { ...prev }
        delete next[sessionId]
        return next
      })
      setProcessing(prev => {
        const next = { ...prev }
        delete next[sessionId]
        return next
      })
      resumedSessionIds.current.delete(sessionId)
    } catch { /* ignore */ }
  }, [activeId])

  // Clear history for active session
  const clearActiveHistory = useCallback(async () => {
    if (!activeId) return
    try {
      await fetch(`/api/sessions/${activeId}/history`, { method: 'DELETE' })
      setMsgs(prev => ({ ...prev, [activeId]: [] }))
      setProcessing(prev => ({ ...prev, [activeId]: false }))
    } catch { /* ignore */ }
  }, [activeId])

  // Left-pane view toggle
  const toggleLeftView = useCallback(() => {
    if (!activeId) return
    setLeftView(prev => ({
      ...prev,
      [activeId]: prev[activeId] === 'notepad' ? 'chat' : 'notepad',
    }))
  }, [activeId])


  // Resizer
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    dragging.current = true
    const handleMouseMove = (e: MouseEvent) => {
      if (!dragging.current || !containerRef.current) return
      const rect = containerRef.current.getBoundingClientRect()
      const totalWidth = rect.width
      const x = e.clientX - rect.left
      const ratio = Math.max(
        MIN_CHAT_WIDTH / totalWidth,
        Math.min(1 - MIN_PDF_WIDTH / totalWidth, x / totalWidth),
      )
      setChatRatio(ratio)
    }
    const handleMouseUp = () => {
      dragging.current = false
      document.removeEventListener('mousemove', handleMouseMove)
      document.removeEventListener('mouseup', handleMouseUp)
      document.body.style.cursor = ''
      document.body.style.userSelect = ''
      if (resizerRef.current) {
        resizerRef.current.style.background = 'var(--dn-border)'
      }
    }
    document.body.style.cursor = 'col-resize'
    document.body.style.userSelect = 'none'
    document.addEventListener('mousemove', handleMouseMove)
    document.addEventListener('mouseup', handleMouseUp)
  }, [])

  const activeSession = sessions.find(s => s.id === activeId)
  const activeLeftView = (activeId && leftView[activeId]) || 'chat'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', position: 'fixed', inset: 0, overflow: 'hidden', background: 'var(--dn-black)' }}>

      {/* Session tab bar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: '0',
        borderBottom: '1px solid var(--dn-border)',
        background: 'var(--dn-black)',
        minHeight: '32px',
        overflowX: 'auto',
        flexShrink: 0,
      }}>
        {sessions.map(s => (
          <div
            key={s.id}
            onClick={() => setActiveId(s.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: '6px',
              padding: '6px 12px',
              cursor: 'pointer',
              borderRight: '1px solid var(--dn-border)',
              background: s.id === activeId ? 'var(--dn-bg)' : 'transparent',
              borderBottom: s.id === activeId ? '2px solid var(--al-brand)' : '2px solid transparent',
              fontFamily: 'var(--font-mono)', fontSize: '11px',
              color: s.id === activeId ? 'var(--dn-text-bright)' : '#fff',
              fontWeight: s.id === activeId ? 700 : 400,
              whiteSpace: 'nowrap',
              transition: 'background 0.1s, color 0.1s',
            }}
          >
            {s.paper_dir && <span style={{ color: 'var(--al-brand)', fontSize: '9px' }}>●</span>}
            <span>{s.label}</span>
            {processing[s.id] && <span style={{ color: 'var(--dn-warning)', fontSize: '9px' }}>●</span>}
            <span
              onClick={(e) => { e.stopPropagation(); deleteSession(s.id) }}
              style={{
                color: 'var(--dn-text-dim)', fontSize: '10px', marginLeft: '4px',
                cursor: 'pointer', padding: '0 2px',
              }}
              title="Close session"
            >✕</span>
          </div>
        ))}
        <button
          onClick={() => {
            setNewLabel('')
            setShowNewSession(true)
          }}
          style={{
            background: 'transparent', border: '1px solid var(--al-brand)',
            borderRadius: '3px',
            color: 'var(--al-brand)', fontFamily: 'var(--font-mono)', fontSize: '11px',
            padding: '3px 10px', margin: '4px 8px', cursor: 'pointer', whiteSpace: 'nowrap',
          }}
        >+ NEW</button>
        <div style={{ marginLeft: 'auto', padding: '6px 12px', whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)', fontSize: '11px' }}>
          <span style={{ color: 'var(--al-brand)', fontWeight: 700 }}>ALFRED</span>
          {appVersion && <span style={{ color: 'var(--dn-text-bright, #fff)', fontSize: '10px', fontWeight: 400 }}> v{appVersion}</span>}
        </div>
      </div>

      {/* New session modal */}
      {showNewSession && (
        <div style={{
          position: 'fixed', inset: 0, zIndex: 200,
          background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={() => setShowNewSession(false)}>
          <div style={{
            background: 'var(--dn-bg-lt, #1e1e1e)', border: '1px solid var(--dn-border-lt, #444)',
            borderRadius: '6px', padding: '20px', width: '340px',
            fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--dn-text, #ccc)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '16px', color: 'var(--al-brand)' }}>
              New Session
            </div>
            <label style={{ display: 'block', marginBottom: '4px', color: 'var(--dn-text-dim, #888)' }}>Label (optional)</label>
            <input
              style={{
                width: '100%', boxSizing: 'border-box', padding: '6px 8px', marginBottom: '16px',
                background: 'var(--dn-bg, #121212)', border: '1px solid var(--dn-border, #333)',
                borderRadius: '3px', color: 'var(--dn-text, #ccc)', fontFamily: 'var(--font-mono)', fontSize: '12px',
              }}
              value={newLabel}
              onChange={e => setNewLabel(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') { createSession(newLabel || undefined); setShowNewSession(false) } }}
              placeholder="e.g. Research on transformers"
              autoFocus
            />
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button onClick={() => setShowNewSession(false)} style={{
                background: 'transparent', border: '1px solid var(--dn-border-lt, #444)',
                color: 'var(--dn-text-dim, #888)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                padding: '4px 12px', borderRadius: '3px', cursor: 'pointer',
              }}>CANCEL</button>
              <button onClick={() => { createSession(newLabel || undefined); setShowNewSession(false) }} style={{
                background: 'var(--al-brand)', border: 'none',
                color: 'var(--dn-black, #000)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                padding: '4px 12px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700,
              }}>CREATE</button>
            </div>
          </div>
        </div>
      )}

      {/* No sessions placeholder */}
      {sessions.length === 0 && (
        <div style={{
          flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexDirection: 'column', gap: '16px',
          fontFamily: 'var(--font-mono)', color: 'var(--dn-text-dim)',
        }}>
          <span style={{ fontSize: '14px' }}>No sessions yet</span>
          <button
            onClick={() => createSession()}
            style={{
              background: 'var(--al-brand)', border: 'none',
              color: 'var(--dn-black)', fontFamily: 'var(--font-mono)', fontSize: '12px',
              padding: '8px 20px', borderRadius: '4px', cursor: 'pointer', fontWeight: 700,
            }}
          >Create Session</button>
        </div>
      )}

      {/* Main content */}
      {activeSession && (
        <div
          ref={containerRef}
          style={{
            display: 'flex',
            flex: 1,
            overflow: 'hidden',
          }}
        >
          {/* Chat / Notepad pane */}
          <div style={{ width: `${chatRatio * 100}%`, minWidth: MIN_CHAT_WIDTH, height: '100%' }}>
            {activeLeftView === 'notepad' && activeSession?.paper_dir ? (
              <Notepad
                key={`notepad-${activeId}`}
                sessionId={activeId!}
                onToggleView={toggleLeftView}
              />
            ) : (
              <TerminalChat
                key={activeId}
                sessionId={activeId!}
                events={msgs[activeId!] || []}
                isProcessing={processing[activeId!] || false}
                wsStatus={status}
                onSend={sendMessage}
                onCancel={cancelActive}
                onClear={clearActiveHistory}
                hasPaper={!!activeSession?.paper_dir}
                onToggleView={toggleLeftView}
              />
            )}
          </div>

          {/* Resizer */}
          <div
            ref={resizerRef}
            onMouseDown={handleMouseDown}
            style={{
              width: '4px',
              cursor: 'col-resize',
              background: 'var(--dn-border)',
              flexShrink: 0,
              transition: 'background 0.15s',
            }}
            onMouseEnter={(e) => {
              (e.target as HTMLDivElement).style.background = 'var(--al-brand)'
            }}
            onMouseLeave={(e) => {
              if (!dragging.current) {
                (e.target as HTMLDivElement).style.background = 'var(--dn-border)'
              }
            }}
          />

          {/* PDF pane */}
          <div style={{ flex: 1, minWidth: MIN_PDF_WIDTH, height: '100%' }}>
            <PdfViewer key={`pdf-${activeId}`} sessionId={activeId!} />
          </div>
        </div>
      )}
    </div>
  )
}
