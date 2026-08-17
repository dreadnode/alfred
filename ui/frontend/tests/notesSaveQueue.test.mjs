import assert from 'node:assert/strict'
import test from 'node:test'

import { loadTypeScript } from './loadTypeScript.mjs'

const sourceUrl = new URL('../src/notesSaveQueue.ts', import.meta.url)
const { NotesSaveQueue } = await loadTypeScript(sourceUrl)

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

test('serializes writes and coalesces waiting edits to the newest text', async () => {
  const writes = []
  const requests = []
  const statuses = []
  let currentText = 'original'
  let activeWrites = 0
  let maxActiveWrites = 0

  const queue = new NotesSaveQueue('original', {
    save: async text => {
      writes.push(text)
      activeWrites += 1
      maxActiveWrites = Math.max(maxActiveWrites, activeWrites)
      const request = deferred()
      requests.push(request)
      await request.promise
      activeWrites -= 1
    },
    getCurrentText: () => currentText,
    onStatusChange: status => statuses.push(status),
  })

  currentText = 'first'
  const idle = queue.enqueue('first')
  currentText = 'middle'
  void queue.enqueue('middle')
  currentText = 'latest'
  void queue.enqueue('latest')

  assert.deepEqual(writes, ['first'])
  requests[0].resolve()
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(writes, ['first', 'latest'])
  requests[1].resolve()
  await idle

  assert.equal(maxActiveWrites, 1)
  assert.equal(queue.isDirty('latest'), false)
  assert.equal(statuses.at(-1), 'saved')
})

test('re-saves original text when an older edit is already in flight', async () => {
  const writes = []
  const requests = []
  let currentText = 'original'

  const queue = new NotesSaveQueue('original', {
    save: async text => {
      writes.push(text)
      const request = deferred()
      requests.push(request)
      await request.promise
    },
    getCurrentText: () => currentText,
    onStatusChange: () => {},
  })

  currentText = 'temporary edit'
  const idle = queue.enqueue('temporary edit')
  currentText = 'original'
  void queue.enqueue('original', true)

  requests[0].resolve()
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(writes, ['temporary edit', 'original'])
  requests[1].resolve()
  await idle
  assert.equal(queue.isDirty('original'), false)
})

test('leaves failed text dirty so a later save can retry it', async () => {
  const statuses = []
  let attempts = 0
  const queue = new NotesSaveQueue('', {
    save: async () => {
      attempts += 1
      if (attempts === 1) throw new Error('network failure')
    },
    getCurrentText: () => 'notes',
    onStatusChange: status => statuses.push(status),
  })

  await queue.enqueue('notes')
  assert.equal(queue.isDirty('notes'), true)
  assert.equal(statuses.at(-1), 'unsaved')

  await queue.enqueue('notes')
  assert.equal(attempts, 2)
  assert.equal(queue.isDirty('notes'), false)
  assert.equal(statuses.at(-1), 'saved')
})
