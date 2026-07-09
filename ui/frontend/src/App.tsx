import { useCallback, useRef, useState } from 'react'
import TerminalChat from './components/TerminalChat'
import PdfViewer from './components/PdfViewer'

const MIN_CHAT_WIDTH = 300
const MIN_PDF_WIDTH = 300
const DEFAULT_CHAT_RATIO = 0.5

export default function App() {
  const [chatRatio, setChatRatio] = useState(DEFAULT_CHAT_RATIO)
  const dragging = useRef(false)
  const containerRef = useRef<HTMLDivElement>(null)
  const resizerRef = useRef<HTMLDivElement>(null)

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

  return (
    <div
      ref={containerRef}
      style={{
        display: 'flex',
        height: '100vh',
        width: '100vw',
        overflow: 'hidden',
        background: 'var(--dn-black)',
      }}
    >
      {/* Chat pane */}
      <div style={{ width: `${chatRatio * 100}%`, minWidth: MIN_CHAT_WIDTH, height: '100%' }}>
        <TerminalChat />
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
        <PdfViewer />
      </div>
    </div>
  )
}
