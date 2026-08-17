import assert from 'node:assert/strict'
import test from 'node:test'

import { loadTypeScript } from './loadTypeScript.mjs'

const sourceUrl = new URL('../src/imageAttachments.ts', import.meta.url)
const {
  MAX_IMAGE_COUNT,
  MAX_IMAGE_TOTAL_BYTES,
  MAX_IMAGE_TOTAL_MIB,
  planImageSelection,
  resolveImageMediaType,
} = await loadTypeScript(sourceUrl)

function file(name, type, size) {
  return { name, type, size }
}

test('accepts only the backend-supported image formats', () => {
  assert.equal(resolveImageMediaType(file('figure.png', 'image/png', 1)), 'image/png')
  assert.equal(resolveImageMediaType(file('photo.JPG', '', 1)), 'image/jpeg')
  assert.equal(resolveImageMediaType(file('figure.webp', 'application/octet-stream', 1)), 'image/webp')
  assert.equal(resolveImageMediaType(file('vector.svg', 'image/svg+xml', 1)), null)
  assert.equal(resolveImageMediaType(file('scan.tiff', 'image/tiff', 1)), null)
})

test('plans multiple images within the count and total-size limits', () => {
  const files = [
    file('one.png', 'image/png', 100),
    file('two.jpg', 'image/jpeg', 200),
  ]
  const plan = planImageSelection([], files)
  assert.deepEqual(plan.accepted.map(({ file: accepted }) => accepted.name), ['one.png', 'two.jpg'])
  assert.deepEqual(plan.errors, [])
})

test('rejects attachments beyond the shared count limit', () => {
  const existing = Array.from({ length: MAX_IMAGE_COUNT }, (_, index) => ({
    data: '', media_type: 'image/png', name: `${index}.png`, size: 1,
  }))
  const plan = planImageSelection(existing, [file('extra.png', 'image/png', 1)])
  assert.equal(plan.accepted.length, 0)
  assert.deepEqual(plan.errors, [`Only ${MAX_IMAGE_COUNT} images may be attached`])
})

test('applies the byte limit across existing and newly selected images', () => {
  const existing = [{
    data: '', media_type: 'image/png', name: 'large.png', size: MAX_IMAGE_TOTAL_BYTES - 1,
  }]
  const plan = planImageSelection(existing, [file('extra.png', 'image/png', 2)])
  assert.equal(plan.accepted.length, 0)
  assert.deepEqual(plan.errors, [
    `Attached images exceed the ${MAX_IMAGE_TOTAL_MIB}MB total limit`,
  ])
})

test('reports empty and unsupported files instead of silently ignoring them', () => {
  const plan = planImageSelection([], [
    file('empty.png', 'image/png', 0),
    file('notes.txt', 'text/plain', 10),
  ])
  assert.equal(plan.accepted.length, 0)
  assert.deepEqual(plan.errors, [
    'empty.png is empty',
    'notes.txt is not a supported image',
  ])
})
