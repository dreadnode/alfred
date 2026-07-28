import { useCallback, useEffect, useRef, useState } from 'react'
import TerminalChat from './components/TerminalChat'
import PdfViewer from './components/PdfViewer'

const MIN_CHAT_WIDTH = 300
const MIN_PDF_WIDTH = 300
const DEFAULT_CHAT_RATIO = 0.5

interface Paper {
  slug: string
  title: string
  active: boolean
}

export default function App() {
  const [chatRatio, setChatRatio] = useState(DEFAULT_CHAT_RATIO)
  const dragging = useRef(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const resizerRef = useRef<HTMLDivElement>(null)

  // Workspace state
  const [workspace, setWorkspace] = useState(false)
  const [papers, setPapers] = useState<Paper[]>([])
  const [paperKey, setPaperKey] = useState(0)
  const [showNewPaper, setShowNewPaper] = useState(false)
  const [newPaperTitle, setNewPaperTitle] = useState('')
  const [newPaperError, setNewPaperError] = useState('')
  const [newPaperSaving, setNewPaperSaving] = useState(false)

  // Fetch config + papers on mount
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => {
        setWorkspace(data.workspace || false)
        if (data.workspace) {
          fetch('/api/papers')
            .then(r => r.json())
            .then(d => setPapers(d.papers || []))
            .catch(() => {})
        }
      })
      .catch(() => {})
  }, [paperKey])

  const switchPaper = useCallback(async (slug: string) => {
    try {
      const res = await fetch('/api/papers/switch', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slug }),
      })
      const data = await res.json()
      if (data.error) return
      setPaperKey(k => k + 1)
    } catch { /* ignore */ }
  }, [])

  const createPaper = useCallback(async () => {
    const title = newPaperTitle.trim()
    if (!title) { setNewPaperError('Title is required'); return }
    setNewPaperSaving(true)
    setNewPaperError('')
    try {
      const res = await fetch('/api/papers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      const data = await res.json()
      if (data.error) { setNewPaperError(data.error); return }
      setShowNewPaper(false)
      setNewPaperTitle('')
      setPaperKey(k => k + 1)
    } catch (e) {
      setNewPaperError(`Failed: ${e}`)
    } finally {
      setNewPaperSaving(false)
    }
  }, [newPaperTitle])

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

  const activePaper = papers.find(p => p.active)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh', width: '100vw', overflow: 'hidden', background: 'var(--dn-black)' }}>

      {/* Paper switcher bar (workspace mode only) */}
      {workspace && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '10px',
          padding: '6px 16px',
          borderBottom: '1px solid var(--dn-border)',
          background: 'var(--dn-black)',
          fontFamily: 'var(--font-mono)', fontSize: '11px',
          flexShrink: 0, position: 'relative',
        }}>
          <span style={{ color: 'var(--dn-text-dim)', marginRight: '4px' }}>PAPER</span>
          <select
            value={activePaper?.slug || ''}
            onChange={e => switchPaper(e.target.value)}
            style={{
              background: 'var(--dn-bg)', border: '1px solid var(--dn-border)',
              borderRadius: '3px', color: 'var(--dn-text)', padding: '3px 6px',
              fontFamily: 'var(--font-mono)', fontSize: '11px', cursor: 'pointer',
            }}
          >
            {papers.map(p => (
              <option key={p.slug} value={p.slug}>{p.title}</option>
            ))}
          </select>
          <button
            onClick={() => { setNewPaperTitle(''); setNewPaperError(''); setShowNewPaper(true) }}
            style={{
              background: 'transparent', border: '1px solid var(--dn-border-lt, #444)',
              color: '#008080', fontFamily: 'var(--font-mono)', fontSize: '11px',
              padding: '2px 8px', borderRadius: '3px', cursor: 'pointer',
            }}
          >+ NEW</button>

          {/* New paper modal */}
          {showNewPaper && (
            <div style={{
              position: 'fixed', inset: 0, zIndex: 200,
              background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
            }} onClick={() => setShowNewPaper(false)}>
              <div style={{
                background: 'var(--dn-bg-lt, #1e1e1e)', border: '1px solid var(--dn-border-lt, #444)',
                borderRadius: '6px', padding: '20px', width: '340px',
                fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--dn-text, #ccc)',
              }} onClick={e => e.stopPropagation()}>
                <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '16px', color: 'var(--dn-accent, #4caf50)' }}>
                  New Paper
                </div>
                <label style={{ display: 'block', marginBottom: '4px', color: 'var(--dn-text-dim, #888)' }}>Title</label>
                <input
                  style={{
                    width: '100%', boxSizing: 'border-box', padding: '6px 8px', marginBottom: '16px',
                    background: 'var(--dn-bg, #121212)', border: '1px solid var(--dn-border, #333)',
                    borderRadius: '3px', color: 'var(--dn-text, #ccc)', fontFamily: 'var(--font-mono)', fontSize: '12px',
                  }}
                  value={newPaperTitle}
                  onChange={e => setNewPaperTitle(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter') createPaper() }}
                  placeholder="My New Paper"
                  autoFocus
                />
                {newPaperError && (
                  <div style={{ color: 'var(--dn-error, #f44336)', marginBottom: '12px', fontSize: '11px' }}>{newPaperError}</div>
                )}
                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
                  <button onClick={() => setShowNewPaper(false)} style={{
                    background: 'transparent', border: '1px solid var(--dn-border-lt, #444)',
                    color: 'var(--dn-text-dim, #888)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                    padding: '4px 12px', borderRadius: '3px', cursor: 'pointer',
                  }}>CANCEL</button>
                  <button onClick={createPaper} disabled={newPaperSaving} style={{
                    background: 'var(--dn-accent, #4caf50)', border: 'none',
                    color: 'var(--dn-black, #000)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                    padding: '4px 12px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700,
                    opacity: newPaperSaving ? 0.6 : 1,
                  }}>{newPaperSaving ? 'CREATING...' : 'CREATE'}</button>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Main content */}
      <div
        ref={containerRef}
        style={{
          display: 'flex',
          flex: 1,
          overflow: 'hidden',
        }}
      >
        {/* Chat pane */}
        <div style={{ width: `${chatRatio * 100}%`, minWidth: MIN_CHAT_WIDTH, height: '100%' }}>
          <TerminalChat key={`chat-${paperKey}`} />
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
            (e.target as HTMLDivElement).style.background = 'var(--dn-accent)'
          }}
          onMouseLeave={(e) => {
            if (!dragging.current) {
              (e.target as HTMLDivElement).style.background = 'var(--dn-border)'
            }
          }}
        />

        {/* PDF pane */}
        <div style={{ flex: 1, minWidth: MIN_PDF_WIDTH, height: '100%' }}>
          <PdfViewer key={`pdf-${paperKey}`} />
        </div>
      </div>
    </div>
  )
}
