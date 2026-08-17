import assert from 'node:assert/strict'
import test from 'node:test'

import { loadTypeScript } from './loadTypeScript.mjs'

const sourceUrl = new URL('../src/eventHistory.ts', import.meta.url)
const {
  appendBoundedEvent,
  applyRoutedChatEvent,
  boundEventHistory,
  routeChatEvent,
} = await loadTypeScript(sourceUrl)

test('bounds an oversized reconnect history to its newest events', () => {
  assert.deepEqual(boundEventHistory([1, 2, 3, 4], 3), [2, 3, 4])
})

test('bounds live appends without reordering the newest events', () => {
  assert.deepEqual(appendBoundedEvent([1, 2, 3], 4, 3), [2, 3, 4])
})

test('handles a disabled event window without retaining data', () => {
  assert.deepEqual(boundEventHistory([1], 0), [])
  assert.deepEqual(appendBoundedEvent([1], 2, 0), [])
})

test('a one-event window retains only the new event', () => {
  assert.deepEqual(appendBoundedEvent([1, 2], 3, 1), [3])
})

test('routes reconnect history as a bounded replacement and marks it idle', () => {
  const routed = routeChatEvent(JSON.stringify({
    type: 'history',
    session_id: 's1',
    events: [
      { type: 'user_message', content: 'old' },
      { type: 'generation', content: 'new' },
    ],
  }), 1)

  assert.deepEqual(routed, {
    sessionId: 's1',
    mode: 'replace',
    events: [{ type: 'generation', content: 'new' }],
    markIdle: true,
    refreshSessions: false,
  })
  assert.deepEqual(
    applyRoutedChatEvent([{ type: 'error', message: 'stale' }], routed, 1),
    [{ type: 'generation', content: 'new' }],
  )
})

test('routes agent completion as a bounded append and session refresh', () => {
  const routed = routeChatEvent(JSON.stringify({
    type: 'agent_end',
    session_id: 's1',
  }))

  assert.equal(routed.markIdle, true)
  assert.equal(routed.refreshSessions, true)
  assert.deepEqual(
    applyRoutedChatEvent([{ type: 'user_message' }], routed, 1),
    [{ type: 'agent_end', session_id: 's1' }],
  )
})

test('rejects malformed or unroutable WebSocket messages', () => {
  assert.equal(routeChatEvent('{broken'), null)
  assert.equal(routeChatEvent(JSON.stringify({ type: 'agent_end' })), null)
  assert.equal(routeChatEvent(JSON.stringify([])), null)
})
