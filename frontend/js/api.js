/**
 * API client — centralized HTTP calls to the backend.
 */
const API = {
  BASE_URL: window.location.origin,

  async uploadFiles(files) {
    const formData = new FormData();
    for (const file of files) {
      formData.append('files', file);
    }
    const res = await fetch(`${this.BASE_URL}/api/documents/upload`, {
      method: 'POST',
      body: formData,
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || 'Upload failed');
    }
    return res.json();
  },

  async getDocuments() {
    const res = await fetch(`${this.BASE_URL}/api/documents`);
    if (!res.ok) throw new Error('Failed to fetch documents');
    return res.json();
  },

  async deleteDocument(docId) {
    const res = await fetch(`${this.BASE_URL}/api/documents/${docId}`, {
      method: 'DELETE',
    });
    if (!res.ok) throw new Error('Failed to delete document');
    return res.json();
  },

  /**
   * Stream chat response via SSE.
   * @param {string} query
   * @param {boolean} useThinking
   * @param {function} onSources - called with sources array
   * @param {function} onToken - called with each token string
   * @param {function} onDone - called when streaming is complete
   * @param {function} onError - called on error
   */
  async streamChat(query, useThinking, onSources, onToken, onDone, onError) {
    try {
      const res = await fetch(`${this.BASE_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, top_k: 5, use_thinking: useThinking }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || 'Chat request failed');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === 'sources') onSources(data.data);
            else if (data.type === 'token') onToken(data.data);
            else if (data.type === 'done') onDone();
          } catch (e) { /* skip malformed lines */ }
        }
      }
      onDone();
    } catch (err) {
      onError(err.message);
    }
  },

  async getHealth() {
    try {
      const res = await fetch(`${this.BASE_URL}/api/health`);
      if (!res.ok) throw new Error('Health check failed');
      return res.json();
    } catch {
      return null;
    }
  },
};
