import { useCallback, useEffect, useRef, useState } from 'react'

import { NotesSaveQueue, type SaveStatus } from '../notesSaveQueue'

interface NotepadProps {
  sessionId: string
  onToggleView: () => void
}

export default function Notepad({ sessionId, onToggleView }: NotepadProps) {
  const [content, setContent] = useState('')
  const [loading, setLoading] = useState(true)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('saved')
  const [darkMode, setDarkMode] = useState(() => {
    try { return localStorage.getItem('notepad-dark-mode') !== '0' }
    catch { return true }
  })

  const contentRef = useRef(content)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(false)
  contentRef.current = content

  const saveQueueRef = useRef<NotesSaveQueue | null>(null)
  if (saveQueueRef.current === null) {
    saveQueueRef.current = new NotesSaveQueue('', {
      save: async (text, keepalive) => {
        const res = await fetch(`/api/sessions/${sessionId}/notes`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content: text }),
          keepalive,
        })
        const data = await res.json()
        if (!res.ok || data.error) throw new Error(data.error || 'Failed to save notes')
      },
      getCurrentText: () => contentRef.current,
      onStatusChange: status => {
        if (mountedRef.current) setSaveStatus(status)
      },
    })
  }
  const saveQueue = saveQueueRef.current

  useEffect(() => {
    mountedRef.current = true
    return () => { mountedRef.current = false }
  }, [])

  useEffect(() => {
    let cancelled = false
    fetch(`/api/sessions/${sessionId}/notes`)
      .then(r => r.json())
      .then(data => {
        if (cancelled) return
        const text = data.content || ''
        setContent(text)
        saveQueue.setSavedText(text)
        setSaveStatus('saved')
        setLoading(false)
      })
      .catch(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [saveQueue, sessionId])

  // Save on unmount if dirty
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      void saveQueue.enqueue(contentRef.current, true)
    }
  }, [saveQueue])

  const handleChange = useCallback((e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const text = e.target.value
    setContent(text)
    setSaveStatus('unsaved')
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { void saveQueue.enqueue(text) }, 1000)
  }, [saveQueue])

  const handleBlur = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    void saveQueue.enqueue(contentRef.current)
  }, [saveQueue])

  const toggleDark = useCallback(() => {
    setDarkMode(prev => {
      const next = !prev
      try { localStorage.setItem('notepad-dark-mode', next ? '1' : '0') } catch {}
      return next
    })
  }, [])

  const bg = darkMode ? 'var(--dn-bg, #121212)' : '#fafafa'
  const fg = darkMode ? 'var(--dn-text, #ccc)' : '#1a1a1a'
  const caretColor = darkMode ? 'var(--al-brand, #4fc3f7)' : '#1a1a1a'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--dn-black)' }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '12px 16px',
        borderBottom: '1px solid var(--dn-border)',
        background: 'var(--dn-black)',
        flexShrink: 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span style={{
            display: 'inline-flex', border: '1px solid var(--dn-border)', borderRadius: '3px',
            fontFamily: 'var(--font-mono)', fontSize: '11px', userSelect: 'none', overflow: 'hidden',
          }}>
            <span
              role="button" tabIndex={0}
              onClick={onToggleView}
              onKeyDown={e => { if (e.key === 'Enter') onToggleView() }}
              style={{ padding: '2px 8px', cursor: 'pointer', color: 'var(--dn-text-dim)', background: 'transparent' }}
              title="Switch to agent chat"
            >Agent</span>
            <span style={{
              padding: '2px 8px', background: 'var(--al-brand)', color: 'var(--dn-black)', fontWeight: 600,
            }}>Notepad</span>
          </span>
          <span style={{ color: 'var(--dn-text-dim, #666)', fontSize: '10px', fontFamily: 'var(--font-mono)' }}>
            {saveStatus === 'saving' ? 'saving...' : saveStatus === 'unsaved' ? '●' : ''}
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          <span
            role="button" tabIndex={0}
            onClick={toggleDark}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleDark() } }}
            style={{ cursor: 'pointer', fontSize: '14px', opacity: 0.7, userSelect: 'none' }}
            aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          >{darkMode ? '☀️' : '🌙'}</span>
        </div>
      </div>

      {/* Editor */}
      {loading ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--dn-text-dim)' }}>
          Loading...
        </div>
      ) : (
        <textarea
          value={content}
          onChange={handleChange}
          onBlur={handleBlur}
          spellCheck={false}
          style={{
            flex: 1,
            width: '100%',
            boxSizing: 'border-box',
            padding: '16px',
            background: bg,
            color: fg,
            caretColor,
            fontFamily: 'var(--font-mono)',
            fontSize: '13px',
            lineHeight: '1.6',
            border: 'none',
            outline: 'none',
            resize: 'none',
          }}
        />
      )}
    </div>
  )
}
