export const MAX_IMAGE_COUNT = 4
export const MAX_IMAGE_TOTAL_MIB = 16
export const MAX_IMAGE_TOTAL_BYTES = MAX_IMAGE_TOTAL_MIB * 1024 * 1024

export const SUPPORTED_IMAGE_MEDIA_TYPES = [
  'image/gif',
  'image/jpeg',
  'image/png',
  'image/webp',
] as const

export const IMAGE_FILE_ACCEPT = [
  ...SUPPORTED_IMAGE_MEDIA_TYPES,
  '.gif',
  '.jpeg',
  '.jpg',
  '.png',
  '.webp',
].join(',')

const MEDIA_TYPE_BY_EXTENSION: Record<string, string> = {
  '.gif': 'image/gif',
  '.jpeg': 'image/jpeg',
  '.jpg': 'image/jpeg',
  '.png': 'image/png',
  '.webp': 'image/webp',
}

const SUPPORTED_MEDIA_TYPES = new Set<string>(SUPPORTED_IMAGE_MEDIA_TYPES)

export interface ImageAttachment {
  data: string
  media_type: string
  name: string
  size: number
}

export interface PlannedImage {
  file: File
  mediaType: string
}

export interface ImageSelectionPlan {
  accepted: PlannedImage[]
  errors: string[]
}

/** Resolve an allowed MIME type, falling back to a known filename extension. */
export function resolveImageMediaType(file: Pick<File, 'name' | 'type'>): string | null {
  if (SUPPORTED_MEDIA_TYPES.has(file.type)) return file.type
  const extension = file.name.toLowerCase().match(/\.[^.]+$/)?.[0]
  return extension ? MEDIA_TYPE_BY_EXTENSION[extension] ?? null : null
}

/** Select files that fit the shared attachment count and decoded-byte limits. */
export function planImageSelection(
  existing: readonly ImageAttachment[],
  files: readonly File[],
): ImageSelectionPlan {
  const accepted: PlannedImage[] = []
  const errors: string[] = []
  let totalBytes = existing.reduce((total, image) => total + image.size, 0)
  let totalCount = existing.length

  for (const file of files) {
    const mediaType = resolveImageMediaType(file)
    if (!mediaType) {
      errors.push(`${file.name || 'Attachment'} is not a supported image`)
      continue
    }
    if (totalCount >= MAX_IMAGE_COUNT) {
      errors.push(`Only ${MAX_IMAGE_COUNT} images may be attached`)
      continue
    }
    if (file.size <= 0) {
      errors.push(`${file.name || 'Attachment'} is empty`)
      continue
    }
    if (totalBytes + file.size > MAX_IMAGE_TOTAL_BYTES) {
      errors.push(`Attached images exceed the ${MAX_IMAGE_TOTAL_MIB}MB total limit`)
      continue
    }
    accepted.push({ file, mediaType })
    totalBytes += file.size
    totalCount += 1
  }

  return { accepted, errors: [...new Set(errors)] }
}

/** Read a browser File into the base64 portion of a data URL. */
export function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => {
      if (typeof reader.result !== 'string') {
        reject(new Error('Image reader returned non-text data'))
        return
      }
      const separator = reader.result.indexOf(',')
      if (separator < 0 || separator === reader.result.length - 1) {
        reject(new Error('Image reader returned an invalid data URL'))
        return
      }
      resolve(reader.result.slice(separator + 1))
    }
    reader.onerror = () => reject(reader.error ?? new Error('Image could not be read'))
    reader.readAsDataURL(file)
  })
}
