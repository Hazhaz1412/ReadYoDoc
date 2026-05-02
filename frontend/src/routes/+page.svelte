<script>
  import { onMount, tick } from 'svelte';

  const promptStarters = [
    'Summarize the key themes and recurring concerns across the uploaded documents.',
    'What contradictions or inconsistencies exist across these documents?',
    'Create an executive brief with risks, decisions, and next actions from the documents.',
    'List the strongest evidence you found and cite the relevant documents for each point.',
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
    connected: false,
    statusText: 'Checking backend health',
    llmModel: 'qwen3.5:9b',
    embeddingModel: 'bge-m3',
    readyCount: 0,
  };
  let toasts = [];

  $: readyDocuments = documents.filter((doc) => doc.status === 'ready').length;
  $: processingDocuments = documents.filter((doc) => doc.status === 'processing').length;
  $: totalDocuments = documents.length;
  $: canSend = query.trim().length > 0 && !isStreaming;

  onMount(() => {
    loadDocuments();
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
      documents = data.documents || [];
    } catch (error) {
      notify(error.message, 'error');
      setRealtime('error', 'Unable to load live queue');
    }
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
        documents = payload.documents || [];
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
    const index = documents.findIndex((doc) => doc.id === nextDoc.id);
    if (index === -1) {
      documents = [nextDoc, ...documents];
      return;
    }

    const nextDocuments = [...documents];
    nextDocuments[index] = nextDoc;
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
        connected: data.ollama_connected,
        statusText: data.ollama_connected
          ? `Backend healthy · ${data.documents_count} ready`
          : 'Model connectivity degraded',
        llmModel: data.llm_model,
        embeddingModel: data.embedding_model,
        readyCount: data.documents_count,
      };
    } catch {
      health = {
        ...health,
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
        sender: 'Operator',
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
        body: JSON.stringify({ query: trimmed, top_k: 5, use_thinking: thinking }),
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
        }
      }

      patchAssistantMessage(assistantMessage.id, {
        typing: false,
        text: fullText,
        html: fullText ? renderMarkdown(fullText) : '<p>No answer returned.</p>',
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

<div class="relative min-h-screen overflow-hidden">
  <div class="pointer-events-none absolute left-[8%] top-[2%] h-72 w-72 rounded-full bg-sky-400/15 blur-[100px]"></div>
  <div class="pointer-events-none absolute bottom-[6%] right-[10%] h-80 w-80 rounded-full bg-amber-300/10 blur-[110px]"></div>

  <div class="relative grid min-h-screen lg:grid-cols-[370px_minmax(0,1fr)]">
    <aside
      class={`fixed inset-y-0 left-0 z-40 w-[min(92vw,420px)] p-4 transition duration-200 lg:static lg:w-auto lg:translate-x-0 lg:p-6 ${
        sidebarOpen ? 'translate-x-0' : '-translate-x-[108%] lg:translate-x-0'
      }`}
    >
      <div class="glass-panel flex h-full flex-col gap-4 rounded-[32px] bg-[linear-gradient(180deg,rgba(13,28,50,0.96),rgba(8,18,34,0.92))] p-5 shadow-glow">
        <div class="flex items-center gap-4">
          <div class="grid h-14 w-14 place-items-center rounded-[18px] bg-[linear-gradient(135deg,rgba(100,210,255,0.25),rgba(255,186,102,0.26))]">
            <svg class="h-7 w-7 text-white" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7">
              <path d="M12 3L4 7.5v9L12 21l8-4.5v-9L12 3z"></path>
              <path d="M4 7.5L12 12l8-4.5"></path>
              <path d="M12 12v9"></path>
            </svg>
          </div>
          <div>
            <p class="panel-kicker">Private Retrieval</p>
            <h1 class="text-[22px] font-extrabold tracking-tight">RAG Control Center</h1>
          </div>
        </div>

        <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-2">
          <div class="glass-panel rounded-3xl p-4">
            <span class="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-400">Realtime Sync</span>
            <div class="mt-3 flex items-center gap-2 text-sm font-semibold">
              <span class={`signal-dot ${realtimeState}`}></span>
              <span>{realtimeText}</span>
            </div>
          </div>

          <div class="glass-panel rounded-3xl p-4">
            <span class="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-400">Ready Documents</span>
            <div class="mt-3 font-mono text-lg font-semibold text-slate-100">
              {readyDocuments}
              <span class="mx-1 text-slate-500">/</span>
              {totalDocuments}
            </div>
          </div>
        </div>

        <section class="flex min-h-0 flex-1 flex-col gap-4">
          <div class="flex items-start justify-between gap-3">
            <div>
              <p class="panel-kicker">Ingestion</p>
              <h2 class="text-xl font-bold tracking-tight">Knowledge Base</h2>
            </div>
            <span class="rounded-full bg-sky-400/10 px-3 py-1 text-xs font-bold text-sky-300">{totalDocuments}</span>
          </div>

          <button
            class={`group relative overflow-hidden rounded-[28px] border border-dashed p-5 text-left transition ${
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
            <div class="relative flex flex-col gap-3">
              <div class="grid h-11 w-11 place-items-center rounded-2xl bg-white/10">
                <svg class="h-6 w-6 text-slate-100" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8">
                  <path d="M12 16V4"></path>
                  <path d="M7 9l5-5 5 5"></path>
                  <path d="M20 16.5v1.5A2 2 0 0118 20H6a2 2 0 01-2-2v-1.5"></path>
                </svg>
              </div>
              <div>
                <strong class="block text-base font-bold">Drop documents to ingest</strong>
                <p class="mt-1 text-sm leading-6 text-slate-300">
                  PDF, DOCX, TXT, MD. Realtime status appears immediately.
                </p>
              </div>
              <span class="inline-flex w-fit rounded-2xl border border-white/10 bg-white/[0.04] px-4 py-2 text-sm font-semibold text-slate-100">
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

          <div class="flex items-end justify-between gap-3">
            <div>
              <span class="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-400">Live document queue</span>
              <p class="mt-1 text-xs leading-5 text-slate-400">
                Upload, processing, and index readiness in one stream.
              </p>
            </div>
            <span class="text-xs font-medium text-slate-300">{processingDocuments} processing</span>
          </div>

          <div class="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto pr-1">
            {#if documents.length === 0}
              <div class="rounded-[22px] border border-dashed border-white/10 bg-white/[0.02] px-5 py-8 text-center text-sm leading-7 text-slate-400">
                No documents yet.<br />
                Upload a few files to turn this into a searchable knowledge base.
              </div>
            {:else}
              {#each documents as doc (doc.id)}
                <article class="glass-panel animate-rise rounded-[22px] p-4">
                  <div class="flex items-start gap-3">
                    <div class={`grid h-11 w-11 place-items-center rounded-2xl text-xs font-bold tracking-[0.18em] ${
                      doc.file_type === '.pdf'
                        ? 'bg-rose-300/15 text-rose-200'
                        : doc.file_type === '.docx'
                          ? 'bg-sky-300/15 text-sky-200'
                          : doc.file_type === '.md'
                            ? 'bg-amber-300/15 text-amber-200'
                            : 'bg-emerald-300/15 text-emerald-200'
                    }`}>
                      {doc.file_type === '.pdf' ? 'PDF' : doc.file_type === '.docx' ? 'DOC' : doc.file_type === '.md' ? 'MD' : 'TXT'}
                    </div>
                    <div class="min-w-0 flex-1">
                      <div class="truncate text-sm font-bold text-slate-50">{doc.filename}</div>
                      <p class="mt-1 text-xs leading-5 text-slate-400">
                        {doc.status === 'ready'
                          ? `${doc.chunk_count} chunks indexed`
                          : doc.status === 'error'
                            ? 'Processing failed'
                            : doc.status_detail || 'Processing'}
                      </p>
                    </div>
                    <span
                      class={`inline-flex items-center gap-1 rounded-full px-3 py-1 text-[11px] font-bold uppercase tracking-[0.18em] ${
                        doc.status === 'ready'
                          ? 'bg-emerald-300/10 text-emerald-200'
                          : doc.status === 'error'
                            ? 'bg-rose-300/10 text-rose-200'
                            : 'bg-amber-300/10 text-amber-100'
                      }`}
                    >
                      {#if doc.status === 'processing'}
                        <span class="h-3 w-3 animate-spin rounded-full border-2 border-white/20 border-t-current"></span>
                      {/if}
                      {doc.status}
                    </span>
                  </div>

                  <div class="mt-4 flex items-center justify-between gap-3 text-[11px] text-slate-400">
                    <div class="flex flex-wrap items-center gap-3">
                      <span>{formatSize(doc.file_size)}</span>
                      <span>{doc.file_type.replace('.', '').toUpperCase()}</span>
                      {#if doc.error_message}
                        <span class="text-rose-200">Needs attention</span>
                      {/if}
                    </div>
                    <span class="rounded-full bg-white/[0.05] px-3 py-1 font-mono text-slate-300">{doc.progress}%</span>
                  </div>

                  <div class="mt-3 h-2 overflow-hidden rounded-full bg-white/[0.06]">
                    <div
                      class="h-full rounded-full bg-[linear-gradient(90deg,#64d2ff,#ffba66)] transition-all duration-300"
                      style={`width:${Math.max(6, Math.min(doc.progress, 100))}%`}
                    ></div>
                  </div>

                  <div class="mt-3 flex justify-end">
                    <button
                      class="rounded-2xl border border-transparent px-3 py-2 text-xs font-semibold text-slate-400 transition hover:border-rose-300/20 hover:bg-rose-300/10 hover:text-rose-200"
                      type="button"
                      on:click={() => deleteDocument(doc.id)}
                    >
                      Remove
                    </button>
                  </div>
                </article>
              {/each}
            {/if}
          </div>
        </section>

        <section class="glass-panel rounded-[26px] p-4">
          <div class="flex items-center gap-2 text-sm text-slate-300">
            <span class={`signal-dot ${health.connected ? 'connected' : 'error'}`}></span>
            <span>{health.statusText}</span>
          </div>
          <div class="mt-4 grid gap-3 sm:grid-cols-2">
            <div>
              <span class="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-400">LLM</span>
              <strong class="mt-2 block text-sm font-semibold text-slate-100">{health.llmModel}</strong>
            </div>
            <div>
              <span class="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-400">Embedding</span>
              <strong class="mt-2 block text-sm font-semibold text-slate-100">{health.embeddingModel}</strong>
            </div>
          </div>
        </section>
      </div>
    </aside>

    <main class="relative flex min-h-screen min-w-0 flex-col gap-5 px-4 pb-4 pt-20 lg:px-6 lg:pb-6 lg:pt-7">
      <button
        class="glass-panel fixed left-4 top-4 z-50 grid h-11 w-11 place-items-center rounded-2xl lg:hidden"
        type="button"
        aria-label="Toggle sidebar"
        on:click={() => (sidebarOpen = !sidebarOpen)}
      >
        <svg class="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <line x1="3" y1="6" x2="21" y2="6"></line>
          <line x1="3" y1="12" x2="21" y2="12"></line>
          <line x1="3" y1="18" x2="21" y2="18"></line>
        </svg>
      </button>

      <header class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p class="panel-kicker">Modernized Operator View</p>
          <h2 class="max-w-4xl text-3xl font-extrabold tracking-tight text-white md:text-4xl xl:text-[2.6rem]">
            Professional private-AI workflow for your document corpus
          </h2>
        </div>
        <div class="flex flex-wrap gap-2">
          <span class="rounded-full border border-white/10 bg-white/[0.04] px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-slate-300">
            Streaming answers
          </span>
          <span class="rounded-full border border-sky-300/20 bg-sky-400/10 px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-sky-200">
            Live ingestion updates
          </span>
        </div>
      </header>

      <section class="grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_minmax(320px,1fr)]">
        <article class="glass-panel overflow-hidden rounded-[32px] bg-hero-grid p-6">
          <span class="inline-flex rounded-full bg-sky-400/10 px-3 py-2 text-[10px] font-extrabold uppercase tracking-[0.22em] text-sky-200">
            Private by default
          </span>
          <h3 class="mt-4 max-w-3xl text-3xl font-extrabold leading-[1.05] tracking-tight text-white md:text-[2.35rem]">
            Search, cite, and answer from your documents without leaving your network.
          </h3>
          <p class="mt-4 max-w-3xl text-sm leading-7 text-slate-300 md:text-[15px]">
            Ingestion and retrieval status are visible in real time, so operators can trust what the model is using before they ask.
          </p>

          <div class="mt-6 grid gap-3 md:grid-cols-3">
            <div class="glass-panel rounded-[22px] p-4">
              <span class="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-400">Indexed</span>
              <strong class="mt-3 block text-3xl font-extrabold tracking-tight text-white">{readyDocuments}</strong>
              <p class="mt-2 text-xs leading-6 text-slate-400">documents ready for retrieval</p>
            </div>
            <div class="glass-panel rounded-[22px] p-4">
              <span class="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-400">Pipeline</span>
              <strong class="mt-3 block text-3xl font-extrabold tracking-tight text-white">{processingDocuments}</strong>
              <p class="mt-2 text-xs leading-6 text-slate-400">documents actively processing</p>
            </div>
            <div class="glass-panel rounded-[22px] p-4">
              <span class="text-[11px] font-bold uppercase tracking-[0.22em] text-slate-400">Trust Layer</span>
              <strong class="mt-3 block text-3xl font-extrabold tracking-tight text-white">Sources</strong>
              <p class="mt-2 text-xs leading-6 text-slate-400">every answer exposes evidence</p>
            </div>
          </div>
        </article>

        <article class="glass-panel rounded-[32px] p-6">
          <div>
            <p class="panel-kicker">Prompt Starters</p>
            <h3 class="mt-1 text-2xl font-bold tracking-tight text-white">High-signal questions</h3>
          </div>

          <div class="mt-5 grid gap-3">
            {#each promptStarters as prompt}
              <button
                class="rounded-[20px] border border-white/10 bg-white/[0.03] px-4 py-4 text-left text-sm font-semibold leading-6 text-slate-100 transition hover:-translate-y-0.5 hover:border-sky-300/30 hover:bg-sky-400/10"
                type="button"
                on:click={() => applyPrompt(prompt)}
              >
                {prompt}
              </button>
            {/each}
          </div>
        </article>
      </section>

      <section class="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto] gap-5">
        <div bind:this={conversationEl} class="min-h-0 overflow-y-auto pr-1">
          <div class="mx-auto flex max-w-5xl flex-col gap-5 pb-2">
            {#if messages.length === 0}
              <div class="glass-panel rounded-[28px] p-8 text-center text-slate-300">
                <p class="panel-kicker">Ready</p>
                <h3 class="mt-2 text-2xl font-bold tracking-tight text-white">Ask grounded questions about your indexed knowledge base.</h3>
                <p class="mx-auto mt-3 max-w-2xl text-sm leading-7 text-slate-400">
                  Upload a few documents, wait for the queue to settle, then start asking for summaries, contradictions, or evidence-backed answers.
                </p>
              </div>
            {/if}

            {#each messages as message (message.id)}
              <article class="grid animate-rise gap-4 md:grid-cols-[48px_minmax(0,1fr)]">
                <div
                  class={`grid h-12 w-12 place-items-center rounded-[18px] border border-white/10 text-sm font-bold ${
                    message.role === 'assistant'
                      ? 'bg-[linear-gradient(135deg,rgba(100,210,255,0.18),rgba(255,186,102,0.22))]'
                      : 'bg-white/[0.04]'
                  }`}
                >
                  {message.role === 'assistant' ? 'AI' : 'You'}
                </div>

                <div class="min-w-0">
                  <div class="mb-2 flex items-center gap-3">
                    <span class="text-sm font-extrabold text-white">{message.sender}</span>
                    <span class="text-xs text-slate-400">{message.time}</span>
                  </div>

                  <div class={`glass-panel rounded-[24px] p-5 leading-7 ${
                    message.role === 'assistant' ? 'bg-sky-400/[0.03]' : 'bg-white/[0.05]'
                  }`}>
                    {#if message.role === 'assistant'}
                      {#if message.typing}
                        <div class="inline-flex gap-1.5 py-1">
                          <span class="h-2 w-2 animate-bounce rounded-full bg-slate-300/70 [animation-delay:-0.2s]"></span>
                          <span class="h-2 w-2 animate-bounce rounded-full bg-slate-300/70 [animation-delay:-0.1s]"></span>
                          <span class="h-2 w-2 animate-bounce rounded-full bg-slate-300/70"></span>
                        </div>
                      {:else}
                        <div class="message-markdown">
                          {@html message.html}
                        </div>
                      {/if}

                      {#if message.sources?.length}
                        <div class="mt-4 border-t border-white/10 pt-4">
                          <button
                            class="inline-flex items-center gap-2 rounded-full border border-sky-300/20 bg-sky-400/10 px-4 py-2 text-xs font-bold uppercase tracking-[0.18em] text-sky-200"
                            type="button"
                            on:click={() => toggleSources(message.id)}
                          >
                            <svg
                              class={`h-3 w-3 transition ${message.sourcesOpen ? 'rotate-90' : ''}`}
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="2"
                            >
                              <path d="M9 18l6-6-6-6"></path>
                            </svg>
                            Evidence pack · {message.sources.length} source{message.sources.length > 1 ? 's' : ''}
                          </button>

                          {#if message.sourcesOpen}
                            <div class="mt-3 flex flex-col gap-3">
                              {#each message.sources as source}
                                <div class="glass-panel rounded-[18px] p-4 text-sm">
                                  <div class="flex flex-wrap items-center gap-2">
                                    <span class="font-extrabold text-slate-100">{source.source_file}</span>
                                    {#if source.page}
                                      <span class="rounded-full bg-white/[0.05] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-sky-200">
                                        Page {source.page}
                                      </span>
                                    {/if}
                                    <span class="rounded-full bg-white/[0.05] px-2 py-1 text-[10px] font-bold uppercase tracking-[0.18em] text-sky-200">
                                      {Math.round(source.relevance_score * 100)}% match
                                    </span>
                                  </div>
                                  <p class="mt-2 text-xs leading-6 text-slate-400">
                                    {source.content.length > 180 ? `${source.content.slice(0, 180)}...` : source.content}
                                  </p>
                                </div>
                              {/each}
                            </div>
                          {/if}
                        </div>
                      {/if}
                    {:else}
                      <p class="whitespace-pre-wrap text-sm text-slate-100">{message.text}</p>
                    {/if}
                  </div>
                </div>
              </article>
            {/each}
          </div>
        </div>

        <div class="mx-auto w-full max-w-5xl">
          <div class="glass-panel rounded-[30px] bg-[rgba(10,21,38,0.88)] p-4">
            <div class="grid gap-4 xl:grid-cols-[minmax(0,1fr)_auto] xl:items-end">
              <textarea
                bind:this={chatInput}
                bind:value={query}
                class="min-h-[34px] max-h-44 w-full resize-none border-0 bg-transparent text-[15px] leading-7 text-white outline-none placeholder:text-slate-500"
                rows="1"
                maxlength="2000"
                placeholder="Ask grounded questions about the indexed knowledge base..."
                on:input={resizeTextarea}
                on:keydown={(event) => {
                  if (event.key === 'Enter' && !event.shiftKey) {
                    event.preventDefault();
                    sendMessage();
                  }
                }}
              ></textarea>

              <div class="flex flex-col gap-3 xl:items-end">
                <label class="inline-flex items-center gap-3 rounded-full border border-white/10 bg-white/[0.03] px-4 py-3 text-sm font-semibold text-slate-200">
                  <input bind:checked={thinking} class="peer sr-only" type="checkbox" />
                  <span class={`relative h-5 w-9 rounded-full transition ${thinking ? 'bg-sky-400/50' : 'bg-white/15'}`}>
                    <span class={`absolute top-0.5 h-4 w-4 rounded-full bg-white transition ${thinking ? 'left-[18px]' : 'left-0.5'}`}></span>
                  </span>
                  Deep reasoning
                </label>

                <button
                  class="inline-flex items-center justify-center gap-2 rounded-[18px] bg-[linear-gradient(135deg,#64d2ff,#ffba66)] px-5 py-3 text-sm font-extrabold text-ink-950 transition hover:-translate-y-0.5 disabled:cursor-not-allowed disabled:opacity-35"
                  type="button"
                  disabled={!canSend}
                  on:click={sendMessage}
                >
                  <span>Send</span>
                  <svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M22 2L11 13"></path>
                    <path d="M22 2L15 22l-4-9-9-4 20-7z"></path>
                  </svg>
                </button>
              </div>
            </div>

            <div class="mt-3 flex flex-col gap-2 text-xs text-slate-400 sm:flex-row sm:items-center sm:justify-between">
              <span>{query.length} / 2000</span>
              <span>Responses stream with source citations</span>
            </div>
          </div>
        </div>
      </section>
    </main>
  </div>

  <div class="fixed bottom-6 right-6 z-[70] flex max-w-[360px] flex-col gap-3">
    {#each toasts as toast (toast.id)}
      <div
        class={`animate-rise rounded-[20px] border px-4 py-3 text-sm shadow-soft backdrop-blur-xl ${
          toast.type === 'error'
            ? 'border-rose-300/20 bg-rose-400/10 text-rose-100'
            : 'border-emerald-300/20 bg-emerald-400/10 text-emerald-100'
        }`}
      >
        {toast.message}
      </div>
    {/each}
  </div>
</div>
