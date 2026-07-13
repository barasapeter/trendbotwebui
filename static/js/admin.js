(function() {
    let users = [];
    let isLoading = false;

    const userListEl = document.getElementById('userList');
    const emailInput = document.getElementById('emailInput');
    const addButton = document.getElementById('addButton');
    const errorMessage = document.getElementById('errorMessage');
    const toastStack = document.getElementById('toastStack');
    const userCount = document.getElementById('userCount');

    const initialUsersEl = document.getElementById('initial-users');
    let initialUsers = [];
    try {
        initialUsers = JSON.parse(initialUsersEl.textContent);
    } catch (e) {
        console.error('Could not parse initial users:', e);
    }
    users = Array.isArray(initialUsers) ? initialUsers : [];

    function renderUsers() {
        if (users.length === 0) {
            userListEl.innerHTML = `
                <li class="empty-state">
                    <div class="empty-icon">
                        <svg viewBox="0 0 24 24">
                            <rect x="3" y="11" width="18" height="10" rx="2" />
                            <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                            <line x1="12" y1="15" x2="12" y2="17" />
                        </svg>
                    </div>
                    <h3>No one's on the list</h3>
                    <p>Grant access above to let someone in</p>
                </li>
            `;
            updateCount();
            return;
        }

        userListEl.innerHTML = users.map(email => {
            const parts = email.split('@');
            const name = parts[0] || email;
            const domain = parts[1] ? '@' + parts[1] : '';
            return `
                <li class="user-item">
                    <div class="user-info">
                        <span class="status-dot"></span>
                        <span class="user-email">
                            ${escapeHtml(name)}<span class="email-domain">${escapeHtml(domain)}</span>
                        </span>
                    </div>
                    <button class="btn-revoke" data-email="${escapeHtml(email)}">
                        <span class="btn-icon">
                            <svg viewBox="0 0 24 24">
                                <polyline points="3 6 5 6 21 6" />
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                            </svg>
                        </span>
                        <span>Revoke</span>
                    </button>
                </li>
            `;
        }).join('');

        updateCount();

        document.querySelectorAll('[data-email]').forEach(btn => {
            btn.addEventListener('click', function() {
                const email = this.getAttribute('data-email');
                handleDeleteUser(email);
            });
        });
    }

    function updateCount() {
        userCount.innerHTML = `<span class="dot"></span>${users.length} active`;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    function validateEmail(email) {
        return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
    }

    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.classList.add('show');
        emailInput.classList.add('error');
    }

    function clearError() {
        errorMessage.classList.remove('show');
        emailInput.classList.remove('error');
    }

    const ICONS = {
        success: '<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg>',
        error: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg>',
        loading: '<div class="spinner"></div>'
    };

    function showToast(message, type) {
        const toast = document.createElement('div');
        toast.className = 'toast ' + type;
        toast.innerHTML = `<span class="toast-icon">${ICONS[type] || ''}</span><span>${escapeHtml(message)}</span>`;
        toastStack.appendChild(toast);

        if (type !== 'loading') {
            setTimeout(() => toast.remove(), 3200);
        }
        return toast;
    }

    async function handleAddUser() {
        const email = emailInput.value.trim();
        clearError();

        if (!email) {
            showError('Email address is required');
            return;
        }

        if (!validateEmail(email)) {
            showError('Enter a valid email address');
            return;
        }

        if (users.includes(email)) {
            showError('This email is already on the list');
            return;
        }

        users.push(email);
        renderUsers();
        emailInput.value = '';
        emailInput.focus();
        const ok = await saveUsers();
        if (ok) showToast('Access granted', 'success');
    }

    async function handleDeleteUser(email) {
        if (!confirm(`Revoke access for ${email}?`)) {
            return;
        }

        users = users.filter(u => u !== email);
        renderUsers();
        const ok = await saveUsers();
        if (ok) showToast('Access revoked', 'success');
    }

    async function saveUsers() {
        if (isLoading) return false;
        isLoading = true;
        addButton.disabled = true;
        const loadingToast = showToast('Saving changes\u2026', 'loading');

        try {
            const response = await fetch('/admin', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(users)
            });

            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.detail || 'Failed to save changes');
            }
            loadingToast.remove();
            return true;
        } catch (error) {
            console.error('Save error:', error);
            loadingToast.remove();
            showToast('Error: ' + error.message, 'error');
            return false;
        } finally {
            isLoading = false;
            addButton.disabled = false;
        }
    }

    emailInput.addEventListener('input', clearError);
    emailInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            handleAddUser();
        }
    });

    addButton.addEventListener('click', handleAddUser);

    window.handleDeleteUser = handleDeleteUser;

    renderUsers();
})();