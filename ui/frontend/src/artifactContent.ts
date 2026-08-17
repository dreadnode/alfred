interface ArtifactResponse {
  content?: unknown
  error?: unknown
}

/** Load a new artifact snapshot on demand, retaining legacy inline support. */
export async function loadArtifactContent(
  sessionId: string,
  artifactId: unknown,
  inlineContent: string,
  fetchArtifact: typeof fetch = fetch,
): Promise<string> {
  if (typeof artifactId !== 'string' || !artifactId) return inlineContent

  const res = await fetchArtifact(
    `/api/sessions/${encodeURIComponent(sessionId)}/artifacts/${encodeURIComponent(artifactId)}`,
  )
  const data = await res.json() as ArtifactResponse
  if (!res.ok || data.error || typeof data.content !== 'string') {
    throw new Error(typeof data.error === 'string' ? data.error : 'Artifact could not be loaded')
  }
  return data.content
}
