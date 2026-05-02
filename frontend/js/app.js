/**
 * Main application — initializes all modules and handles navigation.
 */
const App = {
  init() {
    // Init modules
    Chat.init();
    Upload.init();

    // Tab navigation
    document.querySelectorAll('.nav-tab').forEach(tab => {
      tab.addEventListener('click', () => this.switchTab(tab.dataset.tab));
    });

    // Mobile menu
    const menuBtn = document.getElementById('mobile-menu-btn');
    const sidebar = document.getElementById('sidebar');
    menuBtn.addEventListener('click', () => sidebar.classList.toggle('open'));

    // Click outside sidebar to close on mobile
    document.querySelector('.main-content').addEventListener('click', () => {
      sidebar.classList.remove('open');
    });

    // Check system health
    this.checkHealth();
    setInterval(() => this.checkHealth(), 30000);
  },

  switchTab(tab) {
    // Update nav buttons
    document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
    document.querySelector(`[data-tab="${tab}"]`).classList.add('active');

    // Show/hide documents panel
    const docsPanel = document.getElementById('documents-panel');
    docsPanel.style.display = tab === 'documents' ? 'block' : 'none';

    if (tab === 'documents') Upload.refreshDocuments();
  },

  async checkHealth() {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    const modelName = document.getElementById('model-name');

    const health = await API.getHealth();
    if (health) {
      dot.className = 'status-dot ' + (health.ollama_connected ? 'connected' : 'error');
      text.textContent = health.ollama_connected
        ? `Connected · ${health.documents_count} docs`
        : 'Ollama disconnected';
      modelName.textContent = health.llm_model;
    } else {
      dot.className = 'status-dot error';
      text.textContent = 'Server offline';
    }
  },
};

// Boot
document.addEventListener('DOMContentLoaded', () => App.init());
