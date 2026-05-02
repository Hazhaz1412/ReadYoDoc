import re

with open('/tmp/page_backup.svelte', 'r') as f:
    original = f.read()

# Extract script content
script_match = re.search(r'<script>(.*?)</script>', original, re.DOTALL)
script_content = script_match.group(1) if script_match else ""

# Modify script content
# 1. Add new state
script_content = script_content.replace(
    "let memoryLimit = 20;",
    """let activeView = 'chat';
  let systemSettings = {
    LLM_MODEL: 'qwen3.5:9b',
    EMBEDDING_MODEL: 'bge-m3',
    VISION_MODEL: 'qwen3-vl:8b',
    VISION_ENABLED: true,
    MEMORY_MAX_MESSAGES: 20,
    CHUNK_SIZE: 500,
    CHUNK_OVERLAP: 50
  };
  let isSavingSettings = false;"""
)

# 2. Add loadSettings and call it in onMount
script_content = script_content.replace(
    "loadDocuments();",
    "loadDocuments();\n    loadSettings();"
)

# 3. Add loadSettings and saveSettings functions
functions_to_add = """
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
"""
script_content = script_content.replace("function connectDocumentStream() {", functions_to_add + "\n  function connectDocumentStream() {")

# 4. Modify submitQuery to use systemSettings.MEMORY_MAX_MESSAGES
script_content = script_content.replace("memory_limit: memoryLimit", "memory_limit: systemSettings.MEMORY_MAX_MESSAGES")

# Construct full Svelte file
# We will use string template for HTML
new_html = """
<svelte:head>
  <title>AI RAG Control Center</title>
</svelte:head>

<div class="relative min-h-screen overflow-hidden">
  <div class="pointer-events-none absolute left-[8%] top-[2%] h-72 w-72 rounded-full bg-sky-400/15 blur-[100px]"></div>
  <div class="pointer-events-none absolute bottom-[6%] right-[10%] h-80 w-80 rounded-full bg-amber-300/10 blur-[110px]"></div>

  <div class="relative grid min-h-screen lg:grid-cols-[280px_minmax(0,1fr)]">
    <aside
      class={`fixed inset-y-0 left-0 z-40 w-[min(92vw,320px)] p-4 transition duration-200 lg:static lg:w-auto lg:translate-x-0 lg:p-6 ${
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

    <main class="relative flex min-h-screen min-w-0 flex-col px-4 pb-4 pt-16 lg:px-6 lg:pb-6 lg:pt-6">
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
        <section class="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto] gap-5">
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

                    {#if message.status === 'thinking'}
                      <div class="flex items-center gap-2 text-sm italic text-amber-200/70">
                        <span class="loading-dots">Thinking</span>
                      </div>
                    {:else if message.status === 'searching'}
                      <div class="flex items-center gap-2 text-sm italic text-sky-300/70">
                        <span class="loading-dots">Searching vector database</span>
                      </div>
                    {:else if message.status === 'generating' || message.status === 'done'}
                      {#if message.content}
                        <div class="prose prose-invert prose-sky max-w-none text-[15px] leading-8 text-slate-200">
                          {@html renderMarkdown(message.content)}
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
                    {/if}
                  </div>
                </article>
              {/each}
            </div>
          </div>

          <form class="glass-panel relative mx-auto flex w-full max-w-4xl flex-col gap-3 rounded-[32px] bg-[linear-gradient(180deg,rgba(15,23,42,0.8),rgba(15,23,42,0.95))] p-4 shadow-[0_8px_32px_-8px_rgba(0,0,0,0.5)]" on:submit|preventDefault={submitQuery}>
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
                  submitQuery();
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
        <section class="mx-auto flex w-full max-w-4xl flex-col gap-6 pt-4">
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
                        {doc.extension.replace('.', '').toUpperCase()}
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
        <section class="mx-auto flex w-full max-w-4xl flex-col gap-6 pt-4">
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
  :global(body) {
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
"""

with open('/tmp/page_new.svelte', 'w') as f:
    f.write("<script>\n" + script_content + "\n</script>\n" + new_html)

print("Created /tmp/page_new.svelte")
