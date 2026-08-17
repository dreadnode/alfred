import { useCallback, useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import { TextLayer } from 'pdfjs-dist'
import { useWebSocket } from '../hooks/useWebSocket'

// Configure pdf.js worker
pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.mjs',
  import.meta.url,
).toString()

// --- Styles ---

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column' as const,
    height: '100%',
    background: 'var(--dn-black)',
    position: 'relative' as const,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 16px',
    borderBottom: '1px solid var(--dn-border)',
    background: 'var(--dn-black)',
    flexShrink: 0,
  },
  headerTitle: {
    color: 'var(--dn-text-muted)',
    fontSize: '13px',
    fontWeight: 500,
    letterSpacing: '0.05em',
  },
  pageInfo: {
    color: 'var(--al-brand)',
    fontSize: '11px',
  },
  viewport: {
    flex: 1,
    overflowY: 'auto' as const,
    padding: '16px',
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    gap: '8px',
  },
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: '100%',
    color: 'var(--dn-text-dim)',
    fontSize: '13px',
  },
  loading: {
    color: 'var(--al-interactive)',
    fontSize: '13px',
  },
}

// --- Component ---

const MAX_TITLE_CHARS = 92

interface PdfViewerProps {
  sessionId?: string
}

export default function PdfViewer({ sessionId }: PdfViewerProps = {}) {
  const [pageCount, setPageCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [darkMode, setDarkMode] = useState(() => { try { return localStorage.getItem('pdf-dark-mode') === '1' } catch { return false } })
  const [zoomLevel, setZoomLevel] = useState(1.0)
  const [pdfVersion, setPdfVersion] = useState(0)
  const [paperTitle, setPaperTitle] = useState('')
  const [showTitleEdit, setShowTitleEdit] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [titleError, setTitleError] = useState('')
  const [titleSaving, setTitleSaving] = useState(false)

  // Fetch paper title from sessions endpoint
  useEffect(() => {
    if (!sessionId) return
    fetch('/api/sessions')
      .then(r => r.json())
      .then(data => {
        const session = (data.sessions || []).find((s: Record<string, unknown>) => s.id === sessionId)
        if (session) setPaperTitle(session.label || '')
      })
      .catch(() => {})
  }, [sessionId])

  const openTitleEdit = useCallback(() => {
    setEditTitle(paperTitle)
    setTitleError('')
    setShowTitleEdit(true)
  }, [paperTitle])

  const closeTitleEdit = useCallback(() => {
    setShowTitleEdit(false)
    setTitleError('')
  }, [])

  const saveTitleEdit = useCallback(async () => {
    const title = editTitle.trim()
    if (!title) { setTitleError('Title is required'); return }
    setTitleSaving(true)
    setTitleError('')
    try {
      const res = await fetch(`/api/sessions/${sessionId}/paper-title`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      const data = await res.json()
      if (data.error) { setTitleError(data.error); return }
      setPaperTitle(data.title)
      if (data.warning) {
        setEditTitle(data.title)
        setTitleError(data.warning)
        return
      }
      setShowTitleEdit(false)
    } catch (e) {
      setTitleError(`Failed to save: ${e}`)
    } finally {
      setTitleSaving(false)
    }
  }, [editTitle, sessionId])

  const scrollRef = useRef<HTMLDivElement>(null)
  const viewportRef = useRef<HTMLDivElement>(null)
  const pdfDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null)

  // Listen for PDF update notifications via callback
  const handlePdfMessage = useCallback((data: string) => {
    try {
      const msg = JSON.parse(data)
      if (msg.type === 'pdf_updated' && (!sessionId || msg.session_id === sessionId)) {
        setPdfVersion(v => v + 1)
      }
    } catch {
      // ignore
    }
  }, [sessionId])

  useWebSocket('/ws/pdf', handlePdfMessage)

  // Load PDF — runs inside useEffect with cancellation token
  useEffect(() => {
    let cancelled = false
    let loadingTask: pdfjsLib.PDFDocumentLoadingTask | null = null

    async function loadPdf() {
      setLoading(true)
      setError(null)

      try {
        const url = `/api/pdf?session_id=${sessionId || ''}&v=${pdfVersion}&t=${Date.now()}`
        loadingTask = pdfjsLib.getDocument(url)
        const pdf = await loadingTask.promise

        if (cancelled) {
          pdf.destroy()
          return
        }

        // Clean up previous doc
        if (pdfDocRef.current) {
          pdfDocRef.current.destroy()
        }
        pdfDocRef.current = pdf
        setPageCount(pdf.numPages)

        // Extract title from PDF metadata or first page text
        try {
          const meta = await pdf.getMetadata()
          const rawTitle = (meta?.info as Record<string, unknown>)?.Title
          const infoTitle = typeof rawTitle === 'string' ? rawTitle.trim() : ''
          if (infoTitle) {
            setPaperTitle(infoTitle)
          } else {
            // Fallback: collect all text at the largest font size on page 1
            const page1 = await pdf.getPage(1)
            const text = await page1.getTextContent()
            let maxHeight = 0
            for (const item of text.items) {
              if ('height' in item) {
                const h = (item as { height: number }).height
                if (h > maxHeight) maxHeight = h
              }
            }
            if (maxHeight > 0) {
              const titleParts: string[] = []
              for (const item of text.items) {
                if ('str' in item && 'height' in item) {
                  const h = (item as { height: number }).height
                  const s = (item as { str: string }).str
                  if (h >= maxHeight * 0.95 && s.trim()) {
                    titleParts.push(s.trim())
                  }
                }
              }
              const title = titleParts.join(' ')
              if (title.length > 3) setPaperTitle(title)
            }
          }
        } catch {
          // Title extraction is best-effort
        }

        const container = viewportRef.current
        const scrollContainer = scrollRef.current
        if (!container || !scrollContainer) return

        // Preserve scroll position across reloads
        const scrollTop = scrollContainer.scrollTop

        // Remove old canvases
        while (container.firstChild) {
          container.removeChild(container.firstChild)
        }

        // Compute a scale that fits pages within the container width
        const containerWidth = Math.max(scrollContainer.clientWidth - 32, 100) // subtract padding, floor at 100
        const firstPage = await pdf.getPage(1)
        const baseViewport = firstPage.getViewport({ scale: 1 })
        const fitScale = Math.min(1.5, containerWidth / baseViewport.width)

        for (let i = 1; i <= pdf.numPages; i++) {
          if (cancelled) return

          const page = await pdf.getPage(i)
          const dpr = window.devicePixelRatio || 1
          const viewport = page.getViewport({ scale: fitScale })
          const cssWidth = Math.floor(viewport.width)
          const cssHeight = Math.floor(viewport.height)

          // Page wrapper — CSS dimensions for layout
          const pageDiv = document.createElement('div')
          pageDiv.style.cssText = `position: relative; width: ${cssWidth}px; height: ${cssHeight}px; box-shadow: 0 2px 12px rgba(0,0,0,0.5);`

          // Canvas renders at dpr×  resolution for crisp text on high-DPI screens
          const canvas = document.createElement('canvas')
          canvas.width = Math.floor(viewport.width * dpr)
          canvas.height = Math.floor(viewport.height * dpr)
          canvas.style.cssText = `display: block; width: ${cssWidth}px; height: ${cssHeight}px;`
          pageDiv.appendChild(canvas)

          // Text layer overlay — uses official pdfjs .textLayer class
          const textDiv = document.createElement('div')
          textDiv.className = 'textLayer'
          pageDiv.appendChild(textDiv)

          container.appendChild(pageDiv)

          // Render at high resolution
          const ctx = canvas.getContext('2d')!
          const hiResViewport = page.getViewport({ scale: fitScale * dpr })
          await page.render({ canvasContext: ctx, viewport: hiResViewport }).promise

          // Text layer uses 1x viewport for CSS positioning
          const textContent = await page.getTextContent()
          const textLayer = new TextLayer({
            textContentSource: textContent,
            container: textDiv,
            viewport,
          })
          await textLayer.render()
        }

        // Restore scroll position
        if (!cancelled) {
          scrollContainer.scrollTop = scrollTop
        }
      } catch (e) {
        if (cancelled) return
        const msg = e instanceof Error ? e.message : String(e)
        if (msg.includes('404') || msg.includes('Missing PDF')) {
          setError('No PDF yet — build the paper first.')
        } else {
          setError(`PDF load error: ${msg}`)
        }
        setPageCount(0)
        setPaperTitle('')
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadPdf()

    return () => {
      cancelled = true
      if (loadingTask) {
        loadingTask.destroy()
      }
    }
  }, [pdfVersion, sessionId])

  // Destroy pdf doc on unmount only
  useEffect(() => {
    return () => {
      if (pdfDocRef.current) {
        pdfDocRef.current.destroy()
        pdfDocRef.current = null
      }
    }
  }, [])

  if (error) {
    return (
      <div style={styles.container}>
        <div style={styles.header}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px' }}>
          <span style={styles.headerTitle}>PDF PREVIEW</span>
          {paperTitle && (
            <span
              role="button" tabIndex={0}
              onClick={openTitleEdit}
              onKeyDown={e => { if (e.key === 'Enter') openTitleEdit() }}
              style={{ color: '#4fc3f7', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline', textDecorationStyle: 'dotted' as const, textUnderlineOffset: '3px' }}
              title="Edit paper title"
            >
              {paperTitle.length > MAX_TITLE_CHARS ? paperTitle.slice(0, MAX_TITLE_CHARS) + '...' : paperTitle}
            </span>
          )}
        </div>
          <span
            role="button" tabIndex={0}
            onClick={() => { const next = !darkMode; setDarkMode(next); localStorage.setItem('pdf-dark-mode', next ? '1' : '0') }}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); const next = !darkMode; setDarkMode(next); localStorage.setItem('pdf-dark-mode', next ? '1' : '0') } }}
            style={{ cursor: 'pointer', fontSize: '14px', opacity: 0.7, userSelect: 'none' }}
            aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          >{darkMode ? '☀️' : '🌙'}</span>
        </div>
        <div style={styles.empty}>{error}</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '16px' }}>
          <span style={styles.headerTitle}>PDF PREVIEW</span>
          {paperTitle && (
            <span
              role="button" tabIndex={0}
              onClick={openTitleEdit}
              onKeyDown={e => { if (e.key === 'Enter') openTitleEdit() }}
              style={{ color: '#4fc3f7', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline', textDecorationStyle: 'dotted' as const, textUnderlineOffset: '3px' }}
              title="Edit paper title"
            >
              {paperTitle.length > MAX_TITLE_CHARS ? paperTitle.slice(0, MAX_TITLE_CHARS) + '...' : paperTitle}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {loading && <span style={styles.loading}>Loading...</span>}
          {pageCount > 0 && (
            <span style={styles.pageInfo}>{pageCount} page{pageCount !== 1 ? 's' : ''}</span>
          )}
          {zoomLevel !== 1.0 && (
            <span
              role="button" tabIndex={0}
              onClick={() => setZoomLevel(1.0)}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setZoomLevel(1.0) } }}
              style={{ ...styles.pageInfo, cursor: 'pointer', textDecoration: 'underline', textDecorationStyle: 'dotted' as const, textUnderlineOffset: '3px' }}
              aria-label="Reset zoom to 100%"
              title="Reset zoom to 100%"
            >{Math.round(zoomLevel * 100)}%</span>
          )}
          <span
            role="button" tabIndex={0}
            onClick={() => { const next = !darkMode; setDarkMode(next); localStorage.setItem('pdf-dark-mode', next ? '1' : '0') }}
            onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); const next = !darkMode; setDarkMode(next); localStorage.setItem('pdf-dark-mode', next ? '1' : '0') } }}
            style={{ cursor: 'pointer', fontSize: '14px', opacity: 0.7, userSelect: 'none' }}
            aria-label={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
            title={darkMode ? 'Switch to light mode' : 'Switch to dark mode'}
          >{darkMode ? '☀️' : '🌙'}</span>
        </div>
      </div>
      {/* Title Edit Modal */}
      {showTitleEdit && (
        <div style={{
          position: 'absolute', inset: 0, zIndex: 100,
          background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center',
        }} onClick={closeTitleEdit}>
          <div style={{
            background: 'var(--dn-bg-lt, #1e1e1e)', border: '1px solid var(--dn-border-lt, #444)',
            borderRadius: '6px', padding: '20px', width: '340px',
            fontFamily: 'var(--font-mono)', fontSize: '12px', color: 'var(--dn-text, #ccc)',
          }} onClick={e => e.stopPropagation()}>
            <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '16px', color: 'var(--al-brand)' }}>
              Paper Title
            </div>

            <input
              style={{
                width: '100%', boxSizing: 'border-box' as const, padding: '6px 8px', marginBottom: '16px',
                background: 'var(--dn-bg, #121212)', border: '1px solid var(--dn-border, #333)',
                borderRadius: '3px', color: 'var(--dn-text, #ccc)', fontFamily: 'var(--font-mono)', fontSize: '12px',
              }}
              value={editTitle}
              onChange={e => setEditTitle(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter') saveTitleEdit() }}
              autoFocus
            />

            {titleError && (
              <div style={{ color: 'var(--dn-error, #f44336)', marginBottom: '12px', fontSize: '11px' }}>{titleError}</div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button onClick={closeTitleEdit} style={{
                background: 'transparent', border: '1px solid var(--dn-border-lt, #444)',
                color: 'var(--dn-text-dim, #888)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                padding: '4px 12px', borderRadius: '3px', cursor: 'pointer',
              }}>CANCEL</button>
              <button onClick={saveTitleEdit} disabled={titleSaving} style={{
                background: 'var(--al-brand)', border: 'none',
                color: 'var(--dn-black, #000)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                padding: '4px 12px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700,
                opacity: titleSaving ? 0.6 : 1,
              }}>{titleSaving ? 'SAVING...' : 'SAVE'}</button>
            </div>
          </div>
        </div>
      )}

      <div
        ref={scrollRef}
        style={styles.viewport}
        onWheel={e => {
          if (e.ctrlKey || e.metaKey) {
            e.preventDefault()
            setZoomLevel(z => {
              const next = z + (e.deltaY < 0 ? 0.05 : -0.05)
              return Math.round(Math.min(3.0, Math.max(0.5, next)) * 20) / 20
            })
          }
        }}
      >
        <div ref={viewportRef} style={{
          transform: `scale(${zoomLevel})`,
          transformOrigin: 'top center',
          ...(darkMode ? { filter: 'invert(1) hue-rotate(180deg)' } : {}),
        }} />
      </div>
    </div>
  )
}
