import assert from 'node:assert/strict'
import test from 'node:test'

import { loadTypeScript } from './loadTypeScript.mjs'

const sourceUrl = new URL('../src/artifactContent.ts', import.meta.url)
const { loadArtifactContent } = await loadTypeScript(sourceUrl)

test('loads a stored artifact by encoded session and artifact IDs', async () => {
  const requests = []
  const fetchArtifact = async url => {
    requests.push(url)
    return {
      ok: true,
      json: async () => ({ content: 'stored snapshot' }),
    }
  }

  const content = await loadArtifactContent(
    'session/with spaces',
    'artifact?1',
    '',
    fetchArtifact,
  )

  assert.equal(content, 'stored snapshot')
  assert.deepEqual(requests, [
    '/api/sessions/session%2Fwith%20spaces/artifacts/artifact%3F1',
  ])
})

test('keeps legacy inline artifacts without making a request', async () => {
  let requested = false
  const fetchArtifact = async () => {
    requested = true
    throw new Error('should not fetch')
  }

  const content = await loadArtifactContent('session', undefined, 'legacy', fetchArtifact)

  assert.equal(content, 'legacy')
  assert.equal(requested, false)
})

test('rejects missing or malformed artifact responses', async () => {
  const fetchArtifact = async () => ({
    ok: true,
    json: async () => ({ error: 'artifact not found' }),
  })

  await assert.rejects(
    loadArtifactContent('session', 'missing', '', fetchArtifact),
    /artifact not found/,
  )
})
