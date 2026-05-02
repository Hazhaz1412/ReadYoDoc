<script>

  import { onMount, tick } from 'svelte';

  const promptStarters = [
    'Summarize the key themes and recurring concerns across the uploaded documents.',
    'What contradictions or inconsistencies exist across these documents?',
    'Create an executive brief with risks, decisions, and next actions from the documents.',
    'List the strongest evidence you found and cite the relevant documents for each point.',
  ];

  const chatModes = [
    {
      value: 'strict',
      label: 'Strict',
      description: 'Only answer from uploaded documents. No off-topic chat.',
    },
    {
      value: 'hybrid',
      label: 'Hybrid',
      description: 'Prefer documents, but can fall back to general answers when needed.',
    },
    {
      value: 'friendly',
      label: 'Friendly',
      description: 'Can chat freely and does not require document grounding for every reply.',
    },
  ];

  let documents = [];
  let messages = [];
  let query = '';
  let thinking = false;
  let isStreaming = false;
  let dragActive = false;
  let sidebarOpen = false;
  let realtimeState = 'connecting';
  let realtimeText = 'Connecting live feed';
  let chatInput;
  let fileInput;
  let conversationEl;
  let ws;
  let reconnectTimer;
  let healthTimer;
  let health = {
    status: 'checking',
    connected: false,
    statusText: 'Checking backend health',
    llmModel: 'qwen3.5:9b',
    embeddingModel: 'bge-m3',
    visionModel: 'qwen3-vl:8b',
    visionEnabled: true,
    documentsCount: 0,
    readyCount: 0,
  };
  let toasts = [];

  // Conversation memory
  let conversationId = null;
  let conversations = [];
  let activeView = 'chat';
  let systemSettings = {
    LLM_MODEL: 'qwen3.5:9b',
    EMBEDDING_MODEL: 'bge-m3',
    VISION_MODEL: 'qwen3-vl:8b',
    VISION_ENABLED: true,
    CHAT_MODE: 'hybrid',
    MEMORY_MAX_MESSAGES: 20,
    CHUNK_SIZE: 500,
    CHUNK_OVERLAP: 50,
    PERSONALIZATION_ENABLED: true
  };
  let isSavingSettings = false;

  // Personalization / Memory
  let memories = [];
  let isLoadingMemories = false;
  let newMemoryText = '';
  let editingMemoryId = null;
  let editingMemoryText = '';

  $: readyDocuments = documents.filter((doc) => doc.status === 'ready').length;
  $: processingDocuments = documents.filter((doc) => doc.status === 'processing').length;
  $: totalDocuments = documents.length;
  $: canSend = query.trim().length > 0 && !isStreaming;

  onMount(() => {
    loadDocuments();
    loadSettings();
    loadConversations();
    loadMemories();
    connectDocumentStream();
    checkHealth();
    healthTimer = setInterval(checkHealth, 30000);

    return () => {
      if (ws) ws.close();
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (healthTimer) clearInterval(healthTimer);
    };
  });

  async function loadDocuments() {
    try {
      const res = await fetch('/api/documents');
      if (!res.ok) throw new Error('Failed to load documents');
      const data = await res.json();
      documents = (data.documents || []).map(normalizeDocument);
    } catch (error) {
      notify(error.message, 'error');
      setRealtime('error', 'Unable to load live queue');
    }
  }

  
  async function loadSettings() {
    try {
      const res = await fetch('/api/settings');
      if (res.ok) {
        const data = await res.json();
        if (data && Object.keys(data).length > 0) {
           systemSettings = { ...systemSettings, ...data };
        }
      }
    } catch (err) {
      console.error('Failed to load settings', err);
    }
  }

  async function saveSettings() {
    isSavingSettings = true;
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(systemSettings)
      });
      if (!res.ok) throw new Error('Failed to save settings');
      notify('Settings saved successfully', 'success');
    } catch (err) {
      notify(err.message, 'error');
    } finally {
      isSavingSettings = false;
    }
  }

  // ─── Memory management ──────────────────────────────────

  async function loadMemories() {
    isLoadingMemories = true;
    try {
      const res = await fetch('/api/memories');
      if (res.ok) {
        const data = await res.json();
        memories = data.memories || [];
      }
    } catch (err) {
      console.error('Failed to load memories', err);
    } finally {
      isLoadingMemories = false;
    }
  }

  async function addMemory() {
    const text = newMemoryText.trim();
    if (!text) return;
    try {
      const res = await fetch('/api/memories', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text })
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed' }));
        throw new Error(err.detail || 'Failed to add memory');
      }
      newMemoryText = '';
      notify('Memory added', 'success');
      await loadMemories();
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  async function updateMemory(id, updates) {
    try {
      const res = await fetch(`/api/memories/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      });
      if (!res.ok) throw new Error('Failed to update memory');
      editingMemoryId = null;
      editingMemoryText = '';
      await loadMemories();
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  async function deleteMemory(id) {
    try {
      const res = await fetch(`/api/memories/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete memory');
      notify('Memory removed', 'success');
      await loadMemories();
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  async function clearAllMemories() {
    if (!window.confirm('Delete all memories? This cannot be undone.')) return;
    try {
      const res = await fetch('/api/memories', { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to clear memories');
      notify('All memories cleared', 'success');
      await loadMemories();
    } catch (err) {
      notify(err.message, 'error');
    }
  }

  function startEditMemory(mem) {
    editingMemoryId = mem.id;
    editingMemoryText = mem.content;
  }

  function cancelEditMemory() {
    editingMemoryId = null;
    editingMemoryText = '';
  }

  function stripMemoryTags(text) {
    return text.replace(/<memory_save>.*?<\/memory_save>/gs, '').replace(/\n{3,}/g, '\n\n').trim();
  }

  function connectDocumentStream() {
    setRealtime('connecting', 'Connecting live feed');
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    ws = new WebSocket(`${protocol}://${window.location.host}/api/documents/ws`);

    ws.addEventListener('open', () => {
      setRealtime('connected', 'Live feed connected');
    });

    ws.addEventListener('message', (event) => {
      const payload = JSON.parse(event.data);
      if (payload.type === 'documents.snapshot') {
        documents = (payload.documents || []).map(normalizeDocument);
        return;
      }

      if (payload.type === 'document.created' || payload.type === 'document.updated') {
        upsertDocument(payload.document);
        return;
      }

      if (payload.type === 'document.deleted') {
        documents = documents.filter((doc) => doc.id !== payload.document_id);
      }
    });

    ws.addEventListener('close', () => {
      setRealtime('connecting', 'Reconnecting live feed');
      scheduleReconnect();
    });

    ws.addEventListener('error', () => {
      setRealtime('error', 'Live feed unavailable');
    });
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectDocumentStream();
    }, 2500);
  }

  function setRealtime(state, label) {
    realtimeState = state;
    realtimeText = label;
  }

  function upsertDocument(nextDoc) {
    const normalizedDoc = normalizeDocument(nextDoc);
    const index = documents.findIndex((doc) => doc.id === normalizedDoc.id);
    if (index === -1) {
      documents = [normalizedDoc, ...documents];
      return;
    }

    const nextDocuments = [...documents];
    nextDocuments[index] = normalizedDoc;
    documents = nextDocuments.sort((a, b) => {
      if (a.upload_date < b.upload_date) return 1;
      if (a.upload_date > b.upload_date) return -1;
      return 0;
    });
  }

  async function checkHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) throw new Error('Health check failed');
      const data = await res.json();
      health = {
        status: data.status,
        connected: data.ollama_connected,
        statusText: data.ollama_connected
          ? `Backend healthy · ${data.documents_count} ready`
          : 'Model connectivity degraded',
        llmModel: data.llm_model,
        embeddingModel: data.embedding_model,
        visionModel: data.vision_model,
        visionEnabled: data.vision_enabled,
        documentsCount: data.documents_count,
        readyCount: data.documents_count,
      };
    } catch {
      health = {
        ...health,
        status: 'offline',
        connected: false,
        statusText: 'Backend offline',
      };
    }
  }

  async function handleFiles(fileList) {
    if (!fileList || fileList.length === 0) return;
    const allowed = ['.pdf', '.docx', '.txt', '.md'];
    const files = Array.from(fileList);

    for (const file of files) {
      const ext = `.${file.name.split('.').pop().toLowerCase()}`;
      if (!allowed.includes(ext)) {
        notify(`Unsupported file: ${file.name}`, 'error');
        return;
      }
    }

    const formData = new FormData();
    for (const file of files) {
      formData.append('files', file);
    }

    try {
      const res = await fetch('/api/documents/upload', {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Upload failed' }));
        throw new Error(error.detail || 'Upload failed');
      }

      const uploaded = await res.json();
      notify(`Queued ${uploaded.length} document${uploaded.length > 1 ? 's' : ''} for ingestion`, 'success');
      fileInput.value = '';
    } catch (error) {
      notify(error.message, 'error');
    }
  }

  async function deleteDocument(id) {
    if (!window.confirm('Delete this document and all of its indexed chunks?')) return;

    try {
      const res = await fetch(`/api/documents/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete document');
      notify('Document removed', 'success');
    } catch (error) {
      notify(error.message, 'error');
    }
  }

  async function sendMessage() {
    const trimmed = query.trim();
    if (!trimmed || isStreaming) return;

    const assistantMessage = {
      id: crypto.randomUUID(),
      role: 'assistant',
      sender: 'RAG Assistant',
      text: '',
      html: '',
      time: nowTime(),
      typing: true,
      sources: [],
      sourcesOpen: false,
    };

    messages = [
      ...messages,
      {
        id: crypto.randomUUID(),
        role: 'user',
        sender: 'You',
        text: trimmed,
        time: nowTime(),
      },
      assistantMessage,
    ];

    query = '';
    isStreaming = true;
    resizeTextarea();
    await scrollConversation();

    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: trimmed,
          top_k: 5,
          use_thinking: thinking,
          conversation_id: conversationId,
          memory_limit: systemSettings.MEMORY_MAX_MESSAGES,
        }),
      });

      if (!res.ok) {
        const error = await res.json().catch(() => ({ detail: 'Chat request failed' }));
        throw new Error(error.detail || 'Chat request failed');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let fullText = '';
      let doneSignal = false;
      let sources = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const payload = JSON.parse(line.slice(6));

          if (payload.type === 'meta') {
            if (payload.data?.conversation_id) {
              conversationId = payload.data.conversation_id;
              loadConversations();
            }
            continue;
          }

          if (payload.type === 'sources') {
            sources = payload.data;
            continue;
          }

          if (payload.type === 'token') {
            fullText += payload.data;
            patchAssistantMessage(assistantMessage.id, {
              typing: false,
              text: fullText,
              html: renderMarkdown(fullText),
            });
            await scrollConversation();
            continue;
          }

          if (payload.type === 'done') {
            doneSignal = true;
          }

          if (payload.type === 'memory_saved') {
            notify(`🧠 Saved: "${payload.data}"`, 'success');
            loadMemories();
          }
        }
      }

      patchAssistantMessage(assistantMessage.id, {
        typing: false,
        text: stripMemoryTags(fullText),
        html: fullText ? renderMarkdown(stripMemoryTags(fullText)) : '<p>No answer returned.</p>',
        sources,
        sourcesOpen: false,
      });

      if (!doneSignal && !fullText) {
        notify('No answer returned', 'error');
      }
    } catch (error) {
      patchAssistantMessage(assistantMessage.id, {
        typing: false,
        text: error.message,
        html: `<p class="text-rose-300">${escapeHtml(error.message)}</p>`,
        sources: [],
      });
      notify(error.message, 'error');
    } finally {
      isStreaming = false;
      await scrollConversation();
    }
  }

  function patchAssistantMessage(id, patch) {
    messages = messages.map((message) => (message.id === id ? { ...message, ...patch } : message));
  }

  function toggleSources(id) {
    messages = messages.map((message) =>
      message.id === id ? { ...message, sourcesOpen: !message.sourcesOpen } : message
    );
  }

  function applyPrompt(text) {
    query = text;
    resizeTextarea();
    chatInput?.focus();
  }

  // ─── Conversation management ───────────────────────────────

  function newChat() {
    conversationId = null;
    messages = [];
    query = '';
    resizeTextarea();
    chatInput?.focus();
  }

  async function loadConversations() {
    try {
      const res = await fetch('/api/conversations');
      if (!res.ok) return;
      const data = await res.json();
      conversations = data.conversations || [];
    } catch { /* silent */ }
  }

  async function loadConversation(convId) {
    try {
      const res = await fetch(`/api/conversations/${convId}/messages?limit=200`);
      if (!res.ok) return;
      const data = await res.json();
      conversationId = convId;
      messages = (data.messages || []).map((msg) => ({
        id: msg.id,
        role: msg.role,
        sender: msg.role === 'assistant' ? 'RAG Assistant' : 'You',
        text: msg.content,
        html: msg.role === 'assistant' ? renderMarkdown(msg.content) : '',
        time: new Date(msg.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        typing: false,
        sources: [],
        sourcesOpen: false,
      }));
      sidebarOpen = false;
      await scrollConversation();
    } catch (error) {
      notify(error.message, 'error');
    }
  }

  async function deleteConversation(convId) {
    if (!window.confirm('Delete this conversation and all messages?')) return;
    try {
      const res = await fetch(`/api/conversations/${convId}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('Failed to delete');
      if (conversationId === convId) newChat();
      await loadConversations();
      notify('Conversation deleted', 'success');
    } catch (error) {
      notify(error.message, 'error');
    }
  }

  function formatConvDate(isoDate) {
    const d = new Date(isoDate);
    const now = new Date();
    if (d.toDateString() === now.toDateString()) return 'Today';
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return d.toLocaleDateString();
  }

  function onDrop(event) {
    event.preventDefault();
    dragActive = false;
    handleFiles(event.dataTransfer.files);
  }

  function resizeTextarea() {
    if (!chatInput) return;
    chatInput.style.height = 'auto';
    chatInput.style.height = `${Math.min(chatInput.scrollHeight, 168)}px`;
  }

  async function scrollConversation() {
    await tick();
    if (conversationEl) {
      conversationEl.scrollTop = conversationEl.scrollHeight;
    }
  }

  function notify(message, type = 'success') {
    const toast = { id: crypto.randomUUID(), message, type };
    toasts = [...toasts, toast];
    setTimeout(() => {
      toasts = toasts.filter((item) => item.id !== toast.id);
    }, 3200);
  }

  function nowTime() {
    return new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function formatSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function normalizeDocument(doc) {
    return {
      ...doc,
      extension: doc.extension ?? doc.file_type ?? '',
      size: doc.size ?? doc.file_size ?? 0,
      progress_msg: doc.progress_msg ?? doc.status_detail ?? '',
    };
  }

  function documentBadge(doc) {
    const ext = (doc.extension || doc.file_type || '').replace('.', '').toUpperCase();
    return ext || 'FILE';
  }

  function renderMarkdown(text) {
    let html = escapeHtml(text);
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
    html = html.replace(/(?:^|\n)- (.+)/gm, '\n<li>$1</li>');
    html = html.replace(/(?:^|\n)\d+\. (.+)/gm, '\n<li>$1</li>');
    html = html.replace(/(?:\s*<li>.*?<\/li>\s*)+/gs, (match) => `<ul>${match}</ul>`);
    html = html.replace(/\n\n+/g, '</p><p>');
    html = html.replace(/\n/g, '<br>');
    return `<p>${html}</p>`;
  }

  function escapeHtml(text) {
    return text
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

</script>

<svelte:head>
  <title>AI RAG Control Center</title>
</svelte:head>

<div class="relative h-screen overflow-hidden">
  <div class="pointer-events-none absolute left-[8%] top-[2%] h-72 w-72 rounded-full bg-sky-400/15 blur-[100px]"></div>
  <div class="pointer-events-none absolute bottom-[6%] right-[10%] h-80 w-80 rounded-full bg-amber-300/10 blur-[110px]"></div>

  <div class="relative grid h-screen lg:grid-cols-[280px_minmax(0,1fr)]">
    <aside
      class={`fixed inset-y-0 left-0 z-40 w-[min(92vw,320px)] p-4 transition duration-200 lg:static lg:h-screen lg:w-auto lg:translate-x-0 lg:p-6 ${
        sidebarOpen ? 'translate-x-0' : '-translate-x-[108%] lg:translate-x-0'
      }`}
    >
      <div class="glass-panel flex h-full flex-col gap-4 rounded-[32px] bg-[linear-gradient(180deg,rgba(13,28,50,0.96),rgba(8,18,34,0.92))] p-5 shadow-glow">
        
        <button
          class="flex items-center justify-center gap-2 rounded-2xl bg-sky-400/10 py-3 font-bold text-sky-200 transition hover:bg-sky-400/20"
          on:click={newChat}
        >
          <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M12 5v14M5 12h14"></path>
          </svg>
          New Chat
        </button>

        <nav class="mt-4 flex flex-col gap-2 border-b border-white/10 pb-4">
          <button 
            class={`flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-semibold transition ${activeView === 'chat' ? 'bg-white/10 text-white' : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'}`}
            on:click={() => activeView = 'chat'}
          >
            💬 Chat
          </button>
          <button 
            class={`flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-semibold transition ${activeView === 'documents' ? 'bg-white/10 text-white' : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'}`}
            on:click={() => activeView = 'documents'}
          >
            📂 Documents
          </button>
          <button 
            class={`flex items-center gap-3 rounded-xl px-4 py-3 text-sm font-semibold transition ${activeView === 'settings' ? 'bg-white/10 text-white' : 'text-slate-400 hover:bg-white/5 hover:text-slate-200'}`}
            on:click={() => activeView = 'settings'}
          >
            ⚙️ Settings
          </button>
        </nav>

        {#if activeView === 'chat'}
          <section class="flex min-h-0 flex-1 flex-col gap-3 pt-2">
            <div class="flex items-center justify-between gap-2 px-2">
              <span class="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-400">Chat History</span>
            </div>
            <div class="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto pr-1">
              {#if conversations.length === 0}
                <p class="px-2 text-xs text-slate-500">No conversations yet</p>
              {:else}
                {#each conversations as conv (conv.id)}
                  <div class="group flex items-center gap-2">
                    <button
                      class={`flex-1 truncate rounded-xl px-3 py-2 text-left text-xs font-semibold transition ${
                        conversationId === conv.id
                          ? 'bg-sky-400/15 text-sky-100'
                          : 'bg-white/[0.03] text-slate-300 hover:bg-white/[0.06]'
                      }`}
                      type="button"
                      on:click={() => loadConversation(conv.id)}
                    >
                      <span class="block truncate">{conv.title}</span>
                      <span class="mt-1 block text-[10px] text-slate-500">{formatConvDate(conv.updated_at)}</span>
                    </button>
                    <button
                      class="grid h-7 w-7 flex-shrink-0 place-items-center rounded-lg text-slate-500 opacity-0 transition hover:bg-rose-300/10 hover:text-rose-300 group-hover:opacity-100"
                      type="button"
                      on:click={() => deleteConversation(conv.id)}
                    >
                      <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M18 6L6 18"></path>
                        <path d="M6 6l12 12"></path>
                      </svg>
                    </button>
                  </div>
                {/each}
              {/if}
            </div>
          </section>
        {/if}

      </div>
    </aside>

    <main class="relative flex h-screen min-h-0 min-w-0 flex-col overflow-hidden px-4 pb-4 pt-16 lg:px-6 lg:pb-6 lg:pt-6">
      <button
        class="glass-panel fixed left-4 top-4 z-50 grid h-11 w-11 place-items-center rounded-2xl lg:hidden"
        type="button"
        on:click={() => (sidebarOpen = !sidebarOpen)}
      >
        <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="3" y1="6" x2="21" y2="6"></line>
          <line x1="3" y1="12" x2="21" y2="12"></line>
          <line x1="3" y1="18" x2="21" y2="18"></line>
        </svg>
      </button>

      {#if activeView === 'chat'}
        <section class="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto] gap-5 overflow-hidden">
          <div bind:this={conversationEl} class="min-h-0 overflow-y-auto pr-1">
            <div class="mx-auto flex max-w-4xl flex-col gap-5 pb-2">
              {#if messages.length === 0}
                <div class="my-12 flex flex-col items-center justify-center text-center">
                  <div class="grid h-16 w-16 place-items-center rounded-3xl bg-[linear-gradient(135deg,rgba(100,210,255,0.15),rgba(255,186,102,0.15))] shadow-glow">
                    <svg class="h-8 w-8 text-sky-200" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                      <path d="M12 3L4 7.5v9L12 21l8-4.5v-9L12 3z"></path>
                      <path d="M4 7.5L12 12l8-4.5"></path>
                      <path d="M12 12v9"></path>
                    </svg>
                  </div>
                  <h2 class="mt-6 text-3xl font-extrabold tracking-tight text-white">How can I help you today?</h2>
                  <p class="mt-3 max-w-xl text-slate-400">
                    I can search through your uploaded documents to find answers, summarize content, or extract key information.
                  </p>

                  <div class="mt-10 grid w-full max-w-3xl gap-3 sm:grid-cols-2 text-left">
                    {#each promptStarters as prompt}
                      <button
                        class="rounded-[20px] border border-white/10 bg-white/[0.03] p-4 text-sm leading-6 text-slate-200 transition hover:-translate-y-0.5 hover:border-sky-300/30 hover:bg-sky-400/10"
                        type="button"
                        on:click={() => applyPrompt(prompt)}
                      >
                        {prompt}
                      </button>
                    {/each}
                  </div>
                </div>
              {/if}

              {#each messages as message (message.id)}
                <article class={`flex animate-rise ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div class={`flex max-w-[min(78%,820px)] items-start gap-4 ${message.role === 'user' ? 'flex-row-reverse' : ''}`}>
                    <div
                      class={`grid h-12 w-12 flex-shrink-0 place-items-center rounded-[18px] border border-white/10 text-sm font-bold ${
                        message.role === 'assistant'
                          ? 'bg-[linear-gradient(135deg,rgba(100,210,255,0.18),rgba(255,186,102,0.22))]'
                          : 'bg-white/[0.04]'
                      }`}
                    >
                      {message.role === 'assistant' ? 'AI' : 'You'}
                    </div>

                    <div class={`min-w-0 ${message.role === 'user' ? 'text-right' : ''}`}>
                      <div class={`mb-2 flex items-center gap-3 ${message.role === 'user' ? 'justify-end' : ''}`}>
                        <span class="text-sm font-extrabold text-white">{message.sender}</span>
                        <span class="text-xs text-slate-400">{message.time}</span>
                      </div>

                      {#if message.role === 'assistant'}
                        {#if message.typing}
                          <div class="inline-flex gap-1.5 py-2">
                            <span class="h-2 w-2 animate-bounce rounded-full bg-slate-300/70 [animation-delay:-0.2s]"></span>
                            <span class="h-2 w-2 animate-bounce rounded-full bg-slate-300/70 [animation-delay:-0.1s]"></span>
                            <span class="h-2 w-2 animate-bounce rounded-full bg-slate-300/70"></span>
                          </div>
                        {:else if message.html}
                          <div class="prose prose-invert prose-sky max-w-none text-[15px] leading-8 text-slate-200">
                            {@html message.html}
                          </div>
                        {:else if message.text}
                          <div class="prose prose-invert prose-sky max-w-none text-[15px] leading-8 text-slate-200">
                            {@html renderMarkdown(message.text)}
                          </div>
                        {/if}

                        {#if message.sources && message.sources.length > 0}
                          <div class="mt-4 flex flex-col gap-2">
                            <span class="text-[11px] font-bold uppercase tracking-[0.2em] text-slate-500">
                              Sources cited
                            </span>
                            <div class="flex flex-wrap gap-2">
                              {#each message.sources as source}
                                <button
                                  class="inline-flex max-w-[200px] items-center gap-2 truncate rounded-xl border border-white/5 bg-white/[0.02] px-3 py-1.5 text-xs text-slate-300 transition hover:bg-white/[0.06]"
                                  title={source.content}
                                >
                                  <svg class="h-3.5 w-3.5 flex-shrink-0 text-sky-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"></path>
                                    <path d="M14 2v6h6"></path>
                                  </svg>
                                  <span class="truncate">{source.source_file}</span>
                                </button>
                              {/each}
                            </div>
                          </div>
                        {/if}
                      {:else}
                        <div class="rounded-[22px] bg-[linear-gradient(180deg,rgba(25,58,104,0.95),rgba(18,44,86,0.98))] px-5 py-3 text-left text-[15px] leading-7 text-sky-50 shadow-[0_10px_30px_-14px_rgba(34,104,211,0.9)] ring-1 ring-sky-300/15">
                          <p class="whitespace-pre-wrap break-words">{message.text}</p>
                        </div>
                      {/if}
                    </div>
                  </div>
                </article>
              {/each}
            </div>
          </div>

          <form class="glass-panel relative mx-auto flex w-full max-w-4xl flex-col gap-3 rounded-[32px] bg-[linear-gradient(180deg,rgba(15,23,42,0.8),rgba(15,23,42,0.95))] p-4 shadow-[0_8px_32px_-8px_rgba(0,0,0,0.5)]" on:submit|preventDefault={sendMessage}>
            <textarea
              bind:this={chatInput}
              bind:value={query}
              class="max-h-40 min-h-[52px] w-full resize-none border-0 bg-transparent px-2 py-2 text-[15px] leading-6 text-white placeholder-slate-400 focus:ring-0"
              placeholder="Message RAG Assistant..."
              rows="1"
              on:input={resizeTextarea}
              on:keydown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  sendMessage();
                }
              }}
            ></textarea>

            <div class="flex items-center justify-between border-t border-white/5 pt-3">
              <div class="flex items-center gap-4 px-2">
                <label class="group flex cursor-pointer items-center gap-2">
                  <div class="relative">
                    <input type="checkbox" bind:checked={thinking} class="peer sr-only" />
                    <div class="h-5 w-9 rounded-full bg-slate-700 transition peer-checked:bg-amber-500/20"></div>
                    <div class="absolute left-1.5 top-1 h-3 w-3 rounded-full bg-slate-400 transition peer-checked:translate-x-4 peer-checked:bg-amber-400"></div>
                  </div>
                  <span class="text-xs font-semibold text-slate-400 transition group-hover:text-slate-200">
                    Deep reasoning
                  </span>
                </label>
              </div>

              <button
                class={`flex items-center justify-center gap-2 rounded-xl px-5 py-2 text-sm font-bold transition ${
                  canSend
                    ? 'bg-sky-400/20 text-sky-200 hover:bg-sky-400/30'
                    : 'cursor-not-allowed bg-white/5 text-slate-500'
                }`}
                type="submit"
                disabled={!canSend}
              >
                Send
                <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <line x1="22" y1="2" x2="11" y2="13"></line>
                  <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
              </button>
            </div>
          </form>
        </section>

      {:else if activeView === 'documents'}
        <section class="mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col gap-6 overflow-y-auto pt-4 pr-1">
          <div class="flex items-center justify-between">
            <h2 class="text-2xl font-bold text-white">Knowledge Base</h2>
            <div class="flex items-center gap-3">
               <span class={`signal-dot ${realtimeState}`}></span>
               <span class="text-sm font-medium text-slate-300">{realtimeText}</span>
            </div>
          </div>

          <button
            class={`group relative overflow-hidden rounded-[28px] border border-dashed p-8 text-center transition ${
              dragActive
                ? 'border-sky-300/70 bg-sky-400/10'
                : 'border-sky-300/30 bg-white/[0.03] hover:-translate-y-0.5 hover:border-sky-300/60 hover:bg-white/[0.05]'
            }`}
            type="button"
            on:click={() => fileInput.click()}
            on:dragover|preventDefault={() => (dragActive = true)}
            on:dragleave={() => (dragActive = false)}
            on:drop={onDrop}
          >
            <div class="pointer-events-none absolute -right-4 -top-8 h-32 w-32 rounded-full bg-sky-300/10 blur-3xl"></div>
            <div class="relative flex flex-col items-center justify-center gap-4">
              <div class="grid h-16 w-16 place-items-center rounded-2xl bg-white/10">
                <svg class="h-8 w-8 text-slate-100" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                  <path d="M12 16V4"></path>
                  <path d="M7 9l5-5 5 5"></path>
                  <path d="M20 16.5v1.5A2 2 0 0118 20H6a2 2 0 01-2-2v-1.5"></path>
                </svg>
              </div>
              <div>
                <strong class="block text-lg font-bold text-white">Drop documents to ingest</strong>
                <p class="mt-2 text-sm leading-6 text-slate-400">
                  PDF, DOCX, TXT, MD. Realtime status appears immediately.
                </p>
              </div>
              <span class="inline-flex w-fit rounded-2xl border border-white/10 bg-white/[0.04] px-5 py-2.5 text-sm font-semibold text-slate-100">
                Choose files
              </span>
            </div>
          </button>
          
          <input
            bind:this={fileInput}
            class="hidden"
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md"
            on:change={(event) => handleFiles(event.currentTarget.files)}
          />

          <div class="glass-panel flex flex-col rounded-[24px] p-6">
            <h3 class="mb-4 text-sm font-bold uppercase tracking-[0.1em] text-slate-400">Uploaded Documents ({documents.length})</h3>
            
            <div class="flex flex-col gap-3">
              {#if documents.length === 0}
                <div class="rounded-[22px] border border-dashed border-white/10 bg-white/[0.02] px-5 py-8 text-center text-sm leading-7 text-slate-400">
                  No documents yet.<br />
                  Upload a few files to turn this into a searchable knowledge base.
                </div>
              {:else}
                {#each documents as doc (doc.id)}
                  <div class="group flex flex-col gap-3 rounded-2xl bg-white/[0.02] p-4 transition hover:bg-white/[0.04]">
                    <div class="flex items-start gap-4">
                      <div class="grid h-12 w-12 flex-shrink-0 place-items-center rounded-xl bg-white/5 text-xs font-black text-slate-400">
                        {documentBadge(doc)}
                      </div>
                      <div class="min-w-0 flex-1">
                        <h4 class="truncate text-sm font-bold text-slate-100" title={doc.filename}>
                          {doc.filename}
                        </h4>
                        <div class="mt-1 flex items-center gap-3 text-xs text-slate-400">
                          <span class="uppercase tracking-wider text-slate-500">{formatSize(doc.size)}</span>
                          {#if doc.status === 'processing'}
                            <span class="flex items-center gap-1.5 text-amber-300">
                              <span class="loading-dots font-semibold">Processing</span>
                            </span>
                          {:else if doc.status === 'ready'}
                            <span class="flex items-center gap-1.5 text-emerald-400">
                              <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
                                <polyline points="20 6 9 17 4 12"></polyline>
                              </svg>
                              <span class="font-semibold">{doc.chunk_count} chunks indexed</span>
                            </span>
                          {:else}
                            <span class="text-rose-400">{doc.error_message || 'Failed'}</span>
                          {/if}
                        </div>
                      </div>
                      <button
                        class="grid h-8 w-8 flex-shrink-0 place-items-center rounded-lg text-slate-500 transition hover:bg-rose-500/10 hover:text-rose-400"
                        title="Remove document"
                        on:click={() => deleteDocument(doc.id)}
                      >
                        <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <path d="M3 6h18M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"></path>
                        </svg>
                      </button>
                    </div>

                    {#if doc.status === 'processing'}
                      <div class="h-1.5 w-full overflow-hidden rounded-full bg-slate-800">
                        <div
                          class="h-full bg-[linear-gradient(90deg,#38bdf8,#818cf8)] transition-all duration-300"
                          style={`width: ${doc.progress || 10}%`}
                        ></div>
                      </div>
                      {#if doc.progress_msg}
                        <p class="text-xs text-slate-500">{doc.progress_msg}</p>
                      {/if}
                    {/if}
                  </div>
                {/each}
              {/if}
            </div>
          </div>
        </section>

      {:else if activeView === 'settings'}
        <section class="mx-auto flex min-h-0 w-full max-w-4xl flex-1 flex-col gap-6 overflow-y-auto pt-4 pr-1">
          <h2 class="text-2xl font-bold text-white">System Settings</h2>

          <div class="grid gap-6 md:grid-cols-2">
            <!-- Models Config -->
            <div class="glass-panel flex flex-col gap-5 rounded-[24px] p-6">
              <h3 class="text-sm font-bold uppercase tracking-[0.1em] text-slate-400 border-b border-white/5 pb-3">Model Configuration</h3>
              
              <div class="flex flex-col gap-2">
                <label class="text-xs font-semibold text-slate-300">LLM Model</label>
                <input type="text" bind:value={systemSettings.LLM_MODEL} class="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-sky-400/50 focus:outline-none" />
              </div>

              <div class="flex flex-col gap-2">
                <label class="text-xs font-semibold text-slate-300">Embedding Model</label>
                <input type="text" bind:value={systemSettings.EMBEDDING_MODEL} class="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-sky-400/50 focus:outline-none" />
              </div>

              <div class="flex flex-col gap-2">
                <div class="flex justify-between items-center">
                  <label class="text-xs font-semibold text-slate-300">Vision Model</label>
                  <label class="relative flex items-center cursor-pointer">
                    <input type="checkbox" bind:checked={systemSettings.VISION_ENABLED} class="sr-only peer">
                    <div class="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-sky-500"></div>
                  </label>
                </div>
                <input type="text" bind:value={systemSettings.VISION_MODEL} disabled={!systemSettings.VISION_ENABLED} class="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-sky-400/50 focus:outline-none disabled:opacity-50" />
              </div>
            </div>

            <!-- RAG & Memory Config -->
            <div class="glass-panel flex flex-col gap-5 rounded-[24px] p-6">
              <h3 class="text-sm font-bold uppercase tracking-[0.1em] text-slate-400 border-b border-white/5 pb-3">RAG & Memory</h3>

              <div class="flex flex-col gap-3">
                <div>
                  <label class="text-xs font-semibold text-slate-300">Chat Mode</label>
                  <p class="mt-1 text-xs leading-5 text-slate-500">Controls how strictly the assistant must stay grounded in your uploaded documents.</p>
                </div>

                <div class="grid gap-2">
                  {#each chatModes as mode}
                    <button
                      type="button"
                      class={`rounded-2xl border px-4 py-3 text-left transition ${
                        systemSettings.CHAT_MODE === mode.value
                          ? 'border-sky-400/40 bg-sky-400/12 shadow-[0_0_0_1px_rgba(56,189,248,0.12)]'
                          : 'border-white/10 bg-white/[0.03] hover:border-white/20 hover:bg-white/[0.05]'
                      }`}
                      on:click={() => (systemSettings.CHAT_MODE = mode.value)}
                    >
                      <div class="flex items-center justify-between gap-3">
                        <span class="text-sm font-bold text-white">{mode.label}</span>
                        {#if systemSettings.CHAT_MODE === mode.value}
                          <span class="rounded-full bg-sky-300/15 px-2 py-1 text-[10px] font-bold uppercase tracking-[0.16em] text-sky-200">Active</span>
                        {/if}
                      </div>
                      <p class="mt-2 text-xs leading-5 text-slate-400">{mode.description}</p>
                    </button>
                  {/each}
                </div>
              </div>
              
              <div class="flex flex-col gap-3">
                <div class="flex justify-between">
                  <label class="text-xs font-semibold text-slate-300">Conversation Memory Limit</label>
                  <span class="text-xs font-bold text-sky-300">{systemSettings.MEMORY_MAX_MESSAGES} messages</span>
                </div>
                <input type="range" min="0" max="100" step="10" bind:value={systemSettings.MEMORY_MAX_MESSAGES} class="h-1.5 w-full appearance-none rounded-full bg-slate-700 outline-none" />
                {#if systemSettings.MEMORY_MAX_MESSAGES > 50}
                  <p class="text-xs text-amber-400">⚠️ High limit may slow down response times.</p>
                {/if}
              </div>

              <div class="flex flex-col gap-2 mt-2">
                <label class="text-xs font-semibold text-slate-300">Chunk Size (Tokens)</label>
                <input type="number" bind:value={systemSettings.CHUNK_SIZE} class="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-sky-400/50 focus:outline-none" />
              </div>

              <div class="flex flex-col gap-2">
                <label class="text-xs font-semibold text-slate-300">Chunk Overlap (Tokens)</label>
                <input type="number" bind:value={systemSettings.CHUNK_OVERLAP} class="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white focus:border-sky-400/50 focus:outline-none" />
              </div>
            </div>
          </div>

          <!-- Personalization Section -->
          <div class="glass-panel flex flex-col gap-5 rounded-[24px] p-6">
            <div class="flex items-center justify-between border-b border-white/5 pb-3">
              <div class="flex items-center gap-3">
                <span class="text-lg">🧠</span>
                <h3 class="text-sm font-bold uppercase tracking-[0.1em] text-slate-400">Personalization</h3>
              </div>
              <div class="flex items-center gap-3">
                <span class="text-xs font-medium text-slate-400">{systemSettings.PERSONALIZATION_ENABLED ? 'On' : 'Off'}</span>
                <label class="relative flex items-center cursor-pointer">
                  <input type="checkbox" bind:checked={systemSettings.PERSONALIZATION_ENABLED} class="sr-only peer">
                  <div class="w-9 h-5 bg-slate-700 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full peer-checked:after:border-white after:content-[''] after:absolute after:top-[2px] after:left-[2px] after:bg-white after:border-gray-300 after:border after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-violet-500"></div>
                </label>
              </div>
            </div>

            <p class="text-xs leading-5 text-slate-400">
              When enabled, the AI will remember your preferences and habits across all conversations. It can auto-detect patterns or save facts when you ask (e.g. "Remember that I prefer bullet points").
            </p>

            {#if systemSettings.PERSONALIZATION_ENABLED}
              <!-- Add new memory -->
              <div class="flex gap-2">
                <input
                  type="text"
                  bind:value={newMemoryText}
                  placeholder="Add a memory manually... (e.g. I prefer concise answers)"
                  maxlength="500"
                  class="flex-1 rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-sm text-white placeholder-slate-500 focus:border-violet-400/50 focus:outline-none"
                  on:keydown={(e) => { if (e.key === 'Enter') addMemory(); }}
                />
                <button
                  class="rounded-xl bg-violet-500/20 px-4 py-2 text-sm font-bold text-violet-200 transition hover:bg-violet-500/30 disabled:opacity-50"
                  on:click={addMemory}
                  disabled={!newMemoryText.trim()}
                >
                  Add
                </button>
              </div>

              <!-- Memory list -->
              {#if isLoadingMemories}
                <div class="flex items-center justify-center py-6">
                  <span class="text-xs text-slate-400">Loading memories...</span>
                </div>
              {:else if memories.length === 0}
                <div class="rounded-[18px] border border-dashed border-white/10 bg-white/[0.02] px-5 py-6 text-center text-sm leading-7 text-slate-400">
                  No memories yet. Chat with the AI and ask it to remember things, or add them manually above.
                </div>
              {:else}
                <div class="flex flex-col gap-2 max-h-80 overflow-y-auto pr-1">
                  {#each memories as mem (mem.id)}
                    <div class="group flex items-start gap-3 rounded-xl bg-white/[0.02] p-3 transition hover:bg-white/[0.04]">
                      {#if editingMemoryId === mem.id}
                        <!-- Editing mode -->
                        <div class="flex-1 flex flex-col gap-2">
                          <input
                            type="text"
                            bind:value={editingMemoryText}
                            maxlength="500"
                            class="w-full rounded-lg border border-violet-400/30 bg-white/5 px-3 py-1.5 text-sm text-white focus:border-violet-400/50 focus:outline-none"
                            on:keydown={(e) => {
                              if (e.key === 'Enter') updateMemory(mem.id, { content: editingMemoryText });
                              if (e.key === 'Escape') cancelEditMemory();
                            }}
                          />
                          <div class="flex gap-2">
                            <button
                              class="rounded-lg bg-violet-500/20 px-3 py-1 text-xs font-semibold text-violet-200 hover:bg-violet-500/30"
                              on:click={() => updateMemory(mem.id, { content: editingMemoryText })}
                            >Save</button>
                            <button
                              class="rounded-lg bg-white/5 px-3 py-1 text-xs font-semibold text-slate-400 hover:bg-white/10"
                              on:click={cancelEditMemory}
                            >Cancel</button>
                          </div>
                        </div>
                      {:else}
                        <!-- Display mode -->
                        <label class="relative mt-0.5 flex cursor-pointer items-center">
                          <input
                            type="checkbox"
                            checked={mem.active}
                            on:change={() => updateMemory(mem.id, { active: !mem.active })}
                            class="sr-only peer"
                          />
                          <div class="h-4 w-4 rounded border border-white/20 bg-white/5 transition peer-checked:border-violet-400 peer-checked:bg-violet-500/30">
                            {#if mem.active}
                              <svg class="h-4 w-4 text-violet-300" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
                                <polyline points="20 6 9 17 4 12"></polyline>
                              </svg>
                            {/if}
                          </div>
                        </label>

                        <div class="flex-1 min-w-0">
                          <p class="text-sm leading-6 {mem.active ? 'text-slate-200' : 'text-slate-500 line-through'}">
                            {mem.content}
                          </p>
                          <div class="mt-1 flex items-center gap-2">
                            <span class="inline-flex items-center gap-1 rounded-md bg-white/5 px-1.5 py-0.5 text-[10px] font-semibold {mem.source === 'auto' ? 'text-sky-400' : 'text-amber-300'}">
                              {mem.source === 'auto' ? '🤖 Auto' : '✍️ Manual'}
                            </span>
                            <span class="text-[10px] text-slate-600">{new Date(mem.created_at).toLocaleDateString()}</span>
                          </div>
                        </div>

                        <div class="flex gap-1 opacity-0 transition group-hover:opacity-100">
                          <button
                            class="grid h-7 w-7 place-items-center rounded-lg text-slate-500 transition hover:bg-white/10 hover:text-slate-200"
                            title="Edit memory"
                            on:click={() => startEditMemory(mem)}
                          >
                            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                              <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7"></path>
                              <path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z"></path>
                            </svg>
                          </button>
                          <button
                            class="grid h-7 w-7 place-items-center rounded-lg text-slate-500 transition hover:bg-rose-500/10 hover:text-rose-400"
                            title="Delete memory"
                            on:click={() => deleteMemory(mem.id)}
                          >
                            <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                              <path d="M18 6L6 18"></path>
                              <path d="M6 6l12 12"></path>
                            </svg>
                          </button>
                        </div>
                      {/if}
                    </div>
                  {/each}
                </div>

                <!-- Clear all -->
                <div class="flex items-center justify-between pt-2 border-t border-white/5">
                  <span class="text-xs text-slate-500">{memories.length} / 50 memories</span>
                  <button
                    class="text-xs font-semibold text-rose-400/70 transition hover:text-rose-300"
                    on:click={clearAllMemories}
                  >
                    Clear all memories
                  </button>
                </div>
              {/if}
            {/if}
          </div>

          <div class="flex items-center justify-between">
            <!-- Health Panel -->
            <div class="flex items-center gap-4 text-xs font-medium text-slate-400 bg-white/5 px-4 py-2.5 rounded-xl border border-white/5">
              <div class="flex items-center gap-2">
                <span class={`h-2 w-2 rounded-full ${health.status === 'healthy' ? 'bg-emerald-400' : 'bg-rose-400'}`}></span>
                {health.status === 'healthy' ? 'System Healthy' : 'Degraded'}
              </div>
              <span class="w-px h-3 bg-white/10"></span>
              <span>{health.documentsCount || 0} Docs</span>
            </div>

            <button
              class="rounded-xl bg-sky-500 hover:bg-sky-400 text-white px-6 py-2.5 text-sm font-bold transition disabled:opacity-50"
              on:click={saveSettings}
              disabled={isSavingSettings}
            >
              {isSavingSettings ? 'Saving...' : 'Save Settings'}
            </button>
          </div>
        </section>
      {/if}

    </main>
  </div>

  <div class="pointer-events-none fixed bottom-6 right-6 z-50 flex flex-col items-end gap-2">
    {#each toasts as toast (toast.id)}
      <div
        class={`pointer-events-auto rounded-xl border px-4 py-3 text-sm font-medium shadow-xl transition-all duration-300 ${
          toast.type === 'error'
            ? 'border-rose-500/20 bg-rose-500/10 text-rose-200'
            : 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200'
        }`}
      >
        {toast.message}
      </div>
    {/each}
  </div>
</div>

<style>
  :global(html),
  :global(body) {
    height: 100%;
    overflow: hidden;
    background-color: #0b1120;
    color: #e2e8f0;
    font-family:
      'Inter',
      -apple-system,
      BlinkMacSystemFont,
      'Segoe UI',
      Roboto,
      Oxygen,
      Ubuntu,
      Cantarell,
      'Open Sans',
      'Helvetica Neue',
      sans-serif;
  }
  .glass-panel {
    background: rgba(30, 41, 59, 0.4);
    backdrop-filter: blur(20px);
    -webkit-backdrop-filter: blur(20px);
    border: 1px solid rgba(255, 255, 255, 0.05);
  }
  .panel-kicker {
    font-size: 0.65rem;
    font-weight: 800;
    text-transform: uppercase;
    letter-spacing: 0.22em;
    color: #94a3b8;
  }
  .signal-dot {
    height: 8px;
    width: 8px;
    border-radius: 50%;
  }
  .signal-dot.connected {
    background-color: #34d399;
    box-shadow: 0 0 12px #34d399;
  }
  .signal-dot.connecting {
    background-color: #fbbf24;
    animation: pulse 1.5s infinite;
  }
  .signal-dot.error {
    background-color: #f87171;
  }
  @keyframes pulse {
    0% { opacity: 1; }
    50% { opacity: 0.4; }
    100% { opacity: 1; }
  }
  .loading-dots::after {
    content: '';
    animation: dots 1.5s steps(4, end) infinite;
  }
  @keyframes dots {
    0%, 20% { content: ''; }
    40% { content: '.'; }
    60% { content: '..'; }
    80%, 100% { content: '...'; }
  }
  .shadow-glow {
    box-shadow: 0 0 40px -10px rgba(125, 211, 252, 0.15);
  }
</style>
