export type SaveStatus = 'saved' | 'saving' | 'unsaved'

interface PendingSave {
  text: string
  keepalive: boolean
}

interface NotesSaveQueueOptions {
  save: (text: string, keepalive: boolean) => Promise<void>
  getCurrentText: () => string
  onStatusChange: (status: SaveStatus) => void
}

/** Serialize note writes while coalescing waiting edits to the newest text. */
export class NotesSaveQueue {
  private readonly save: NotesSaveQueueOptions['save']
  private readonly getCurrentText: NotesSaveQueueOptions['getCurrentText']
  private readonly onStatusChange: NotesSaveQueueOptions['onStatusChange']
  private savedText: string
  private pending: PendingSave | null = null
  private activeText: string | null = null
  private drainPromise: Promise<void> | null = null

  constructor(savedText: string, options: NotesSaveQueueOptions) {
    this.savedText = savedText
    this.save = options.save
    this.getCurrentText = options.getCurrentText
    this.onStatusChange = options.onStatusChange
  }

  setSavedText(text: string): void {
    this.savedText = text
  }

  isDirty(text: string): boolean {
    return text !== this.savedText
  }

  enqueue(text: string, keepalive = false): Promise<void> {
    if (this.pending === null && text === this.activeText) {
      this.onStatusChange('saving')
      return this.drainPromise ?? Promise.resolve()
    }

    // Saved text is only safe to skip when no older write can still replace it.
    if (this.pending === null && this.activeText === null && text === this.savedText) {
      this.onStatusChange('saved')
      return Promise.resolve()
    }

    this.pending = { text, keepalive }
    this.onStatusChange('saving')
    if (this.drainPromise === null) {
      this.drainPromise = this.drain()
    }
    return this.drainPromise
  }

  private async drain(): Promise<void> {
    try {
      while (this.pending !== null) {
        const pending = this.pending
        this.pending = null
        this.activeText = pending.text

        try {
          await this.save(pending.text, pending.keepalive)
          this.savedText = pending.text
        } catch {
          // If a newer edit is waiting, try it. With nothing newer to save,
          // leave the editor dirty so a later blur or edit can retry.
          if (this.pending === null) break
        } finally {
          this.activeText = null
        }
      }
    } finally {
      this.drainPromise = null
      this.onStatusChange(this.getCurrentText() === this.savedText ? 'saved' : 'unsaved')
    }
  }
}
