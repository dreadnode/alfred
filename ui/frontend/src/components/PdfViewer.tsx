import { useCallback, useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
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
  },
  headerTitle: {
    color: 'var(--dn-text-muted)',
    fontSize: '13px',
    fontWeight: 500,
    letterSpacing: '0.05em',
  },
  pageInfo: {
    color: 'var(--dn-text-dim)',
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
    color: 'var(--dn-accent)',
    fontSize: '13px',
  },
}

// --- Component ---

const MAX_TITLE_CHARS = 50

export default function PdfViewer() {
  const [pageCount, setPageCount] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pdfVersion, setPdfVersion] = useState(0)
  const [paperTitle, setPaperTitle] = useState('')
  const [showTitleEdit, setShowTitleEdit] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [titleError, setTitleError] = useState('')
  const [titleSaving, setTitleSaving] = useState(false)

  // Fetch paper title from server config on mount
  useEffect(() => {
    fetch('/api/config')
      .then(r => r.json())
      .then(data => setPaperTitle(data.paper_title || ''))
      .catch(() => {})
  }, [])

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
      const res = await fetch('/api/paper-title', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title }),
      })
      const data = await res.json()
      if (data.error) { setTitleError(data.error); return }
      setPaperTitle(data.title)
      setShowTitleEdit(false)
    } catch (e) {
      setTitleError(`Failed to save: ${e}`)
    } finally {
      setTitleSaving(false)
    }
  }, [editTitle])

  const viewportRef = useRef<HTMLDivElement>(null)
  const pdfDocRef = useRef<pdfjsLib.PDFDocumentProxy | null>(null)

  // Listen for PDF update notifications via callback
  const handlePdfMessage = useCallback((data: string) => {
    try {
      const msg = JSON.parse(data)
      if (msg.type === 'pdf_updated') {
        setPdfVersion(v => v + 1)
      }
    } catch {
      // ignore
    }
  }, [])

  useWebSocket('/ws/pdf', handlePdfMessage)

  // Load PDF — runs inside useEffect with cancellation token
  useEffect(() => {
    let cancelled = false

    async function loadPdf() {
      setLoading(true)
      setError(null)

      let loadingTask: pdfjsLib.PDFDocumentLoadingTask | null = null

      try {
        const url = `/api/pdf?v=${pdfVersion}&t=${Date.now()}`
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

        const container = viewportRef.current
        if (!container) return

        // Preserve scroll position across reloads
        const scrollTop = container.scrollTop

        // Remove old canvases
        while (container.firstChild) {
          container.removeChild(container.firstChild)
        }

        for (let i = 1; i <= pdf.numPages; i++) {
          if (cancelled) return

          const page = await pdf.getPage(i)
          const scale = 1.5
          const viewport = page.getViewport({ scale })

          const canvas = document.createElement('canvas')
          canvas.style.cssText = 'box-shadow: 0 2px 12px rgba(0,0,0,0.5); max-width: 100%;'
          canvas.width = viewport.width
          canvas.height = viewport.height

          container.appendChild(canvas)

          const ctx = canvas.getContext('2d')!
          await page.render({ canvasContext: ctx, viewport }).promise
        }

        // Restore scroll position
        if (!cancelled) {
          container.scrollTop = scrollTop
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
      } finally {
        if (!cancelled) {
          setLoading(false)
        }
      }
    }

    loadPdf()

    return () => {
      cancelled = true
    }
  }, [pdfVersion])

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
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
          <span style={styles.headerTitle}>PDF PREVIEW</span>
          {paperTitle && (
            <span
              onClick={openTitleEdit}
              style={{ color: '#4fc3f7', fontSize: '11px', cursor: 'pointer', textDecoration: 'underline', textDecorationStyle: 'dotted' as const, textUnderlineOffset: '3px' }}
              title="Edit paper title"
            >
              {paperTitle.length > MAX_TITLE_CHARS ? paperTitle.slice(0, MAX_TITLE_CHARS) + '...' : paperTitle}
            </span>
          )}
        </div>
        </div>
        <div style={styles.empty}>{error}</div>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '10px' }}>
          <span style={styles.headerTitle}>PDF PREVIEW</span>
          {paperTitle && (
            <span
              onClick={openTitleEdit}
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
            <div style={{ fontSize: '13px', fontWeight: 700, marginBottom: '16px', color: 'var(--dn-accent, #4caf50)' }}>
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
                background: 'var(--dn-accent, #4caf50)', border: 'none',
                color: 'var(--dn-black, #000)', fontFamily: 'var(--font-mono)', fontSize: '11px',
                padding: '4px 12px', borderRadius: '3px', cursor: 'pointer', fontWeight: 700,
                opacity: titleSaving ? 0.6 : 1,
              }}>{titleSaving ? 'SAVING...' : 'SAVE'}</button>
            </div>
          </div>
        </div>
      )}

      <div style={styles.viewport} ref={viewportRef} />
    </div>
  )
}
