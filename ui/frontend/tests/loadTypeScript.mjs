import { readFile } from 'node:fs/promises'

import { transformWithEsbuild } from 'vite'

export async function loadTypeScript(sourceUrl) {
  const source = await readFile(sourceUrl, 'utf8')
  const transformed = await transformWithEsbuild(source, sourceUrl.pathname, {
    loader: 'ts',
    target: 'es2020',
  })
  const encoded = Buffer.from(transformed.code).toString('base64')
  return import(`data:text/javascript;base64,${encoded}`)
}
