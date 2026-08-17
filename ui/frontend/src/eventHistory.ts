export const MAX_CLIENT_EVENTS = 2_000

export interface ChatEvent {
  type: string
  [key: string]: unknown
}

export interface RoutedChatEvent {
  sessionId: string
  mode: 'append' | 'replace'
  events: ChatEvent[]
  markIdle: boolean
  refreshSessions: boolean
}

/** Keep only the newest events so a long-lived console tab stays memory-bounded. */
export function boundEventHistory<T>(
  events: readonly T[],
  limit = MAX_CLIENT_EVENTS,
): T[] {
  if (limit <= 0) return []
  return events.length <= limit ? [...events] : events.slice(-limit)
}

/** Append one event while retaining the configured newest-event window. */
export function appendBoundedEvent<T>(
  events: readonly T[],
  event: T,
  limit = MAX_CLIENT_EVENTS,
): T[] {
  if (limit <= 0) return []
  if (events.length < limit) return [...events, event]
  return [...events.slice(events.length - limit + 1), event]
}

/** Parse one WebSocket message into the state transition consumed by App. */
export function routeChatEvent(
  data: string,
  limit = MAX_CLIENT_EVENTS,
): RoutedChatEvent | null {
  let candidate: unknown
  try {
    candidate = JSON.parse(data)
  } catch {
    return null
  }
  if (candidate === null || typeof candidate !== 'object' || Array.isArray(candidate)) {
    return null
  }

  const event = candidate as Record<string, unknown>
  const sessionId = event.session_id
  if (typeof sessionId !== 'string' || !sessionId) return null

  if (event.type === 'history') {
    const history = Array.isArray(event.events) ? event.events as ChatEvent[] : []
    return {
      sessionId,
      mode: 'replace',
      events: boundEventHistory(history, limit),
      markIdle: true,
      refreshSessions: false,
    }
  }

  return {
    sessionId,
    mode: 'append',
    events: [event as ChatEvent],
    markIdle: event.type === 'agent_end',
    refreshSessions: event.type === 'agent_end',
  }
}

/** Apply a parsed WebSocket transition to one session's current history. */
export function applyRoutedChatEvent(
  existing: readonly ChatEvent[],
  routed: RoutedChatEvent,
  limit = MAX_CLIENT_EVENTS,
): ChatEvent[] {
  if (routed.mode === 'replace') return routed.events
  return appendBoundedEvent(existing, routed.events[0], limit)
}
