/**
 * Chat interface — handles message display, SSE streaming, and markdown rendering.
 */
const Chat = {
  isStreaming: false,

  init() {
    this.messagesEl = document.getElementById('messages');
    this.inputEl = document.getElementById('chat-input');
    this.sendBtn = document.getElementById('send-button');
    this.charCount = document.getElementById('char-count');
    this.welcomeScreen = document.getElementById('welcome-screen');
    this.thinkingToggle = document.getElementById('thinking-toggle');

    // Send on click
    this.sendBtn.addEventListener('click', () => this.sendMessage());

    // Send on Enter (Shift+Enter for newline)
    this.inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        this.sendMessage();
      }
    });

    // Auto-resize textarea + char count
    this.inputEl.addEventListener('input', () => {
      this.inputEl.style.height = 'auto';
      this.inputEl.style.height = Math.min(this.inputEl.scrollHeight, 120) + 'px';
      const len = this.inputEl.value.length;
      this.charCount.textContent = `${len} / 2000`;
      this.sendBtn.disabled = len === 0 || this.isStreaming;
    });
  },

  async sendMessage() {
    const query = this.inputEl.value.trim();
    if (!query || this.isStreaming) return;

    // Hide welcome screen
    this.welcomeScreen.style.display = 'none';
    this.messagesEl.style.display = 'flex';

    // Add user message
    this.addMessage('user', query);

    // Clear input
    this.inputEl.value = '';
    this.inputEl.style.height = 'auto';
    this.charCount.textContent = '0 / 2000';
    this.sendBtn.disabled = true;
    this.isStreaming = true;

    // Add assistant message placeholder
    const assistantEl = this.addMessage('assistant', '');
    const contentEl = assistantEl.querySelector('.message-content');

    // Show typing indicator
    contentEl.innerHTML = `<div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>`;

    let fullText = '';
    let sources = [];

    const useThinking = this.thinkingToggle.checked;

    await API.streamChat(
      query,
      useThinking,
      // onSources
      (srcData) => { sources = srcData; },
      // onToken
      (token) => {
        if (contentEl.querySelector('.typing-indicator')) {
          contentEl.innerHTML = '';
        }
        fullText += token;
        contentEl.innerHTML = this.renderMarkdown(fullText);
        this.scrollToBottom();
      },
      // onDone
      () => {
        if (sources.length > 0) {
          contentEl.insertAdjacentHTML('beforeend', this.renderSources(sources));
        }
        this.isStreaming = false;
        this.sendBtn.disabled = this.inputEl.value.length === 0;
        this.scrollToBottom();
      },
      // onError
      (errMsg) => {
        contentEl.innerHTML = `<p style="color:var(--error)">⚠️ ${errMsg}</p>`;
        this.isStreaming = false;
        this.sendBtn.disabled = this.inputEl.value.length === 0;
      }
    );
  },

  addMessage(role, content) {
    const time = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    const isUser = role === 'user';
    const avatar = isUser ? '👤' : '🤖';
    const name = isUser ? 'You' : 'AI Assistant';

    const html = `
      <div class="message ${role}">
        <div class="message-avatar">${avatar}</div>
        <div class="message-body">
          <div class="message-header">
            <span class="message-sender">${name}</span>
            <span class="message-time">${time}</span>
          </div>
          <div class="message-content">${isUser ? this.escapeHtml(content) : content}</div>
        </div>
      </div>`;

    this.messagesEl.insertAdjacentHTML('beforeend', html);
    this.scrollToBottom();
    return this.messagesEl.lastElementChild;
  },

  renderSources(sources) {
    const items = sources.map(s => {
      const page = s.page && s.page > 0 ? `<span class="source-page">Page ${s.page}</span>` : '';
      const score = (s.relevance_score * 100).toFixed(0);
      const preview = s.content.length > 120 ? s.content.substring(0, 120) + '...' : s.content;
      return `
        <div class="source-item">
          <div><span class="source-file">📄 ${this.escapeHtml(s.source_file)}</span>${page}<span class="source-score">${score}%</span></div>
          <div class="source-preview">${this.escapeHtml(preview)}</div>
        </div>`;
    }).join('');

    return `
      <div class="sources-container">
        <button class="sources-toggle" onclick="this.classList.toggle('open');this.nextElementSibling.classList.toggle('open')">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18l6-6-6-6"/></svg>
          ${sources.length} source${sources.length > 1 ? 's' : ''} found
        </button>
        <div class="sources-list">${items}</div>
      </div>`;
  },

  renderMarkdown(text) {
    // Simple markdown renderer
    let html = this.escapeHtml(text);

    // Code blocks (```...```)
    html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');
    // Inline code
    html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
    // Bold
    html = html.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Italic
    html = html.replace(/\*(.*?)\*/g, '<em>$1</em>');
    // Bullet lists
    html = html.replace(/^[-*] (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');
    // Numbered lists
    html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
    // Blockquotes
    html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
    // Headers
    html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
    html = html.replace(/^# (.+)$/gm, '<h2>$1</h2>');
    // Paragraphs (double newline)
    html = html.replace(/\n\n/g, '</p><p>');
    // Single newlines inside paragraphs
    html = html.replace(/\n/g, '<br>');

    return `<p>${html}</p>`;
  },

  escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  scrollToBottom() {
    const container = document.getElementById('chat-container');
    container.scrollTop = container.scrollHeight;
  },
};
