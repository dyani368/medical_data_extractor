import type { Source } from './types'

let token: string | null = null
export function setAccessToken(value: string | null) { token = value }
export class ApiError extends Error { constructor(message: string, public status: number) { super(message) } }

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`/api${path}`, { ...options, headers, signal: options.signal ?? AbortSignal.timeout(30000) })
  if (!response.ok) {
    let message = `Request failed (${response.status}). Please try again.`
    try {
      const data = await response.json()
      if (typeof data.detail === 'string') message = data.detail
      else if (Array.isArray(data.detail)) message = data.detail.map((entry: { msg: string }) => entry.msg).join('. ')
    } catch { /* Use the HTTP error if the proxy returned HTML. */ }
    if (response.status === 401 && path !== '/token') window.dispatchEvent(new Event('session-expired'))
    throw new ApiError(message, response.status)
  }
  return response.json() as Promise<T>
}

export function newKey() {
  const bytes = crypto.getRandomValues(new Uint8Array(16))
  return Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('')
}

export async function streamChat(query: string, conversationId: number | undefined, signal: AbortSignal, handlers: {
  text: (text: string) => void; sources: (sources: Source[]) => void; conversation: (id: number) => void
}) {
  const response = await fetch('/api/chat/stream', { method: 'POST', signal,
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ query, ...(conversationId ? { conversation_id: conversationId } : {}) }) })
  if (!response.ok) {
    if (response.status === 401) window.dispatchEvent(new Event('session-expired'))
    const body = await response.json().catch(() => ({}))
    throw new ApiError(body.detail || `Chat failed (${response.status}).`, response.status)
  }
  if (!response.body) throw new Error('The server returned an empty response.')
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = '', completed = false
  function dispatch(block: string) {
    const lines = block.split(/\r?\n/)
    const event = lines.find(line => line.startsWith('event:'))?.slice(6).trim() || 'message'
    const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).replace(/^ /, '')).join('\n')
    if (!data && event !== 'complete') return
    if (event === 'conversation') handlers.conversation(JSON.parse(data).conversation_id)
    else if (event === 'sources') handlers.sources(JSON.parse(data))
    else if (event === 'error') throw new Error(JSON.parse(data).message || 'The answer could not be completed. Please retry.')
    else if (event === 'complete') completed = true
    else if (event === 'message' && data !== '[DONE]') handlers.text(data)
  }
  try {
    while (true) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value, { stream: !done })
      let match: RegExpExecArray | null
      while ((match = /\r?\n\r?\n/.exec(buffer))) {
        dispatch(buffer.slice(0, match.index))
        buffer = buffer.slice(match.index + match[0].length)
      }
      if (done) break
    }
    if (buffer.trim()) dispatch(buffer)
    if (!completed) throw new Error('The connection ended before the answer finished. Please retry.')
  } finally { reader.releaseLock() }
}
