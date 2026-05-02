/**
 * Document upload and management UI logic.
 */
const Upload = {
  init() {
    this.zone = document.getElementById('upload-zone');
    this.fileInput = document.getElementById('file-input');
    this.docList = document.getElementById('document-list');
    this.badge = document.getElementById('doc-count-badge');

    // Click to browse
    this.zone.addEventListener('click', () => this.fileInput.click());
    this.fileInput.addEventListener('change', (e) => this.handleFiles(e.target.files));

    // Drag and drop
    this.zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      this.zone.classList.add('drag-over');
    });
    this.zone.addEventListener('dragleave', () => {
      this.zone.classList.remove('drag-over');
    });
    this.zone.addEventListener('drop', (e) => {
      e.preventDefault();
      this.zone.classList.remove('drag-over');
      this.handleFiles(e.dataTransfer.files);
    });

    // Initial load
    this.refreshDocuments();
    // Poll for status updates every 5s
    this._pollInterval = setInterval(() => this.refreshDocuments(), 5000);
  },

  async handleFiles(fileList) {
    if (!fileList || fileList.length === 0) return;

    const files = Array.from(fileList);
    const allowed = ['.pdf', '.docx', '.txt', '.md'];

    for (const f of files) {
      const ext = '.' + f.name.split('.').pop().toLowerCase();
      if (!allowed.includes(ext)) {
        alert(`Unsupported file: ${f.name}\nAllowed: ${allowed.join(', ')}`);
        return;
      }
    }

    try {
      this.zone.style.opacity = '0.5';
      this.zone.style.pointerEvents = 'none';
      await API.uploadFiles(files);
      this.fileInput.value = '';
      await this.refreshDocuments();
    } catch (err) {
      alert('Upload error: ' + err.message);
    } finally {
      this.zone.style.opacity = '1';
      this.zone.style.pointerEvents = 'auto';
    }
  },

  async refreshDocuments() {
    try {
      const data = await API.getDocuments();
      this.renderDocuments(data.documents);
      this.badge.textContent = data.total;
    } catch { /* silent fail */ }
  },

  renderDocuments(docs) {
    if (!docs.length) {
      this.docList.innerHTML = '<p style="text-align:center;color:var(--text-muted);font-size:13px;padding:20px;">No documents uploaded yet</p>';
      return;
    }

    this.docList.innerHTML = docs.map(doc => {
      const iconMap = { '.pdf': '📕', '.docx': '📘', '.txt': '📄', '.md': '📝' };
      const classMap = { '.pdf': 'pdf', '.docx': 'docx', '.txt': 'txt', '.md': 'md' };
      const icon = iconMap[doc.file_type] || '📄';
      const cls = classMap[doc.file_type] || 'txt';
      const size = this.formatSize(doc.file_size);

      let statusHtml;
      if (doc.status === 'processing') {
        statusHtml = '<span class="doc-status processing"><span class="spinner"></span> Processing</span>';
      } else if (doc.status === 'ready') {
        statusHtml = `<span class="doc-status ready">✓ ${doc.chunk_count} chunks</span>`;
      } else {
        statusHtml = `<span class="doc-status error" title="${doc.error_message || ''}">✗ Error</span>`;
      }

      return `
        <div class="doc-item" data-id="${doc.id}">
          <div class="doc-icon ${cls}">${icon}</div>
          <div class="doc-info">
            <div class="doc-name" title="${doc.filename}">${doc.filename}</div>
            <div class="doc-meta">
              <span>${size}</span>
              ${statusHtml}
            </div>
          </div>
          <button class="doc-delete" onclick="Upload.deleteDoc('${doc.id}')" title="Delete">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/>
            </svg>
          </button>
        </div>`;
    }).join('');
  },

  async deleteDoc(id) {
    if (!confirm('Delete this document and all its chunks?')) return;
    try {
      await API.deleteDocument(id);
      await this.refreshDocuments();
    } catch (err) {
      alert('Delete error: ' + err.message);
    }
  },

  formatSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  },
};
