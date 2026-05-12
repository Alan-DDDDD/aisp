const API_BASE = import.meta.env.VITE_API_BASE || ''

async function request(path, options = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  if (res.status === 204) return null
  return res.json()
}

export function listWorkspaces() {
  return request('/api/workspaces')
}

export function createRoom(workspaceId = 'cs') {
  return request('/api/rooms', {
    method: 'POST',
    body: JSON.stringify({ workspace_id: workspaceId }),
  })
}

export function getRoomMessages(roomId) {
  return request(`/api/rooms/${roomId}/messages`)
}

export function getTrace(traceId) {
  return request(`/api/traces/${traceId}`)
}

export function getHealth() {
  return request('/health')
}

// Admin
export function getAdminWorkspace(id) {
  return request(`/api/admin/workspaces/${id}`)
}

export function getWorkflowYaml(id) {
  return fetch(`${API_BASE}/api/admin/workspaces/${id}/workflow`).then((r) => r.text())
}

export function reloadWorkflow(id) {
  return request(`/api/admin/workspaces/${id}/workflow/reload`, { method: 'POST' })
}

export function listKbDocuments(kbId) {
  return request(`/api/admin/kbs/${kbId}/documents`)
}

export function ingestKbDocument(kbId, body) {
  return request(`/api/admin/kbs/${kbId}/documents`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function uploadKbPdf(kbId, file, { title, category } = {}) {
  const form = new FormData()
  form.append('file', file)
  if (title) form.append('title', title)
  if (category) form.append('category', category)
  const res = await fetch(`${API_BASE}/api/admin/kbs/${kbId}/documents/upload`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`${res.status} ${res.statusText}: ${text}`)
  }
  return res.json()
}

export function listKbChunks(docId) {
  return request(`/api/admin/documents/${docId}/chunks`)
}

export function listTraces(params = {}) {
  const qs = new URLSearchParams(params).toString()
  return request(`/api/admin/traces${qs ? `?${qs}` : ''}`)
}

export function listTickets(workspaceId) {
  const qs = workspaceId ? `?workspace_id=${encodeURIComponent(workspaceId)}` : ''
  return request(`/api/admin/tickets${qs}`)
}

export function listWorkspaceRooms(workspaceId, limit = 20) {
  return request(`/api/admin/workspaces/${workspaceId}/rooms?limit=${limit}`)
}
