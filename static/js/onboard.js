(function() {
    let currentStep = 1;
    const totalSteps = 4;
    const state = {
        api_token: '',
        app_id: '',
        email: '',
    };

    const stepContainer = document.getElementById('stepContainer');
    const feedbackEl = document.getElementById('feedback');
    const feedbackText = document.getElementById('feedbackText');
    const segments = document.querySelectorAll('.progress-segment');
    const labels = document.querySelectorAll('.progress-label');

    function setFeedback(message, type) {
        feedbackEl.className = 'feedback';
        feedbackText.textContent = message;
        const icon = feedbackEl.querySelector('i');
        if (type === 'error') {
            feedbackEl.classList.add('error');
            icon.className = 'fas fa-exclamation-circle';
        } else if (type === 'success') {
            feedbackEl.classList.add('success');
            icon.className = 'fas fa-check-circle';
        } else {
            feedbackEl.classList.add('hidden');
            icon.className = 'fas fa-info-circle';
            return;
        }
    }

    function clearFeedback() {
        feedbackEl.className = 'feedback hidden';
    }

    function updateProgress(activeStep) {
        segments.forEach((seg, idx) => {
            const step = idx + 1;
            seg.classList.remove('active', 'completed');
            if (step === activeStep) seg.classList.add('active');
            else if (step < activeStep) seg.classList.add('completed');
        });

        labels.forEach((label, idx) => {
            const step = idx + 1;
            label.classList.remove('active', 'completed');
            if (step === activeStep) label.classList.add('active');
            else if (step < activeStep) label.classList.add('completed');
        });
    }

    function buildStepHTML(step) {
        let html = '';
        if (step === 1) {
            html = `
                <div class="step-badge"><i class="fas fa-key"></i> Step 1 of 4</div>
                <div class="step-title">Enter your API token</div>
                <div class="step-desc">Your secret key to access the Amy platform.</div>
                <div class="input-group">
                    <label><i class="fas fa-lock"></i> API Token</label>
                    <input type="text" id="apiTokenInput" placeholder="sk_live_..." value="${state.api_token}">
                </div>
                <div class="action-row">
                    <button class="btn btn-primary" id="stepNextBtn">Continue <i class="fas fa-arrow-right"></i></button>
                </div>
            `;
        } else if (step === 2) {
            html = `
                <div class="step-badge"><i class="fas fa-cube"></i> Step 2 of 4</div>
                <div class="step-title">Your App ID</div>
                <div class="step-desc">The unique identifier for your application.</div>
                <div class="input-group">
                    <label><i class="fas fa-qrcode"></i> App ID</label>
                    <input type="text" id="appIdInput" placeholder="app_abc123..." value="${state.app_id}">
                </div>
                <div class="action-row">
                    <button class="btn btn-back" id="stepBackBtn"><i class="fas fa-arrow-left"></i> Back</button>
                    <button class="btn btn-primary" id="stepNextBtn">Next <i class="fas fa-arrow-right"></i></button>
                </div>
            `;
        } else if (step === 3) {
            html = `
                <div class="step-badge"><i class="fas fa-envelope"></i> Step 3 of 4</div>
                <div class="step-title">Your email address</div>
                <div class="step-desc">We'll use this to personalize your experience.</div>
                <div class="input-group">
                    <label><i class="fas fa-at"></i> Email</label>
                    <input type="email" id="emailInput" placeholder="you@example.com" value="${state.email}">
                </div>
                <div class="action-row">
                    <button class="btn btn-back" id="stepBackBtn"><i class="fas fa-arrow-left"></i> Back</button>
                    <button class="btn btn-primary" id="stepNextBtn">Review <i class="fas fa-arrow-right"></i></button>
                </div>
            `;
        } else if (step === 4) {
            html = `
                <div class="step-badge"><i class="fas fa-clipboard-check"></i> Final step</div>
                <div class="step-title">Confirm your details</div>
                <div class="step-desc">Please verify everything is correct before finishing.</div>
                <div class="review-grid">
                    <div class="review-item">
                        <span class="label"><i class="fas fa-key"></i> Token</span>
                        <span class="value">${maskToken(state.api_token)}</span>
                    </div>
                    <div class="review-item">
                        <span class="label"><i class="fas fa-cube"></i> App ID</span>
                        <span class="value">${state.app_id || '—'}</span>
                    </div>
                    <div class="review-item">
                        <span class="label"><i class="fas fa-envelope"></i> Email</span>
                        <span class="value">${state.email || '—'}</span>
                    </div>
                </div>
                <div class="action-row">
                    <button class="btn btn-back" id="stepBackBtn"><i class="fas fa-arrow-left"></i> Back</button>
                    <button class="btn btn-success" id="submitBtn"><i class="fas fa-check"></i> Finish</button>
                </div>
            `;
        }
        return html;
    }

    function renderStep(step) {
        clearFeedback();
        stepContainer.innerHTML = buildStepHTML(step);
        updateProgress(step);
        attachEvents(step);
    }

    function attachEvents(step) {
        if (step === 1) {
            const input = document.getElementById('apiTokenInput');
            const nextBtn = document.getElementById('stepNextBtn');
            if (input) {
                input.addEventListener('input', function(e) {
                    state.api_token = e.target.value.trim();
                });
                if (state.api_token) input.value = state.api_token;
            }
            if (nextBtn) {
                nextBtn.addEventListener('click', function() {
                    const val = document.getElementById('apiTokenInput')?.value?.trim() || '';
                    if (!val) {
                        setFeedback('Please enter your API token.', 'error');
                        return;
                    }
                    state.api_token = val;
                    currentStep = 2;
                    renderStep(2);
                });
                input?.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter') nextBtn.click();
                });
            }
        } else if (step === 2) {
            const input = document.getElementById('appIdInput');
            const nextBtn = document.getElementById('stepNextBtn');
            const backBtn = document.getElementById('stepBackBtn');
            if (input) {
                input.addEventListener('input', function(e) {
                    state.app_id = e.target.value.trim();
                });
                if (state.app_id) input.value = state.app_id;
            }
            if (nextBtn) {
                nextBtn.addEventListener('click', function() {
                    const val = document.getElementById('appIdInput')?.value?.trim() || '';
                    if (!val) {
                        setFeedback('Please enter your App ID.', 'error');
                        return;
                    }
                    state.app_id = val;
                    currentStep = 3;
                    renderStep(3);
                });
                input?.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter') nextBtn.click();
                });
            }
            if (backBtn) {
                backBtn.addEventListener('click', function() {
                    currentStep = 1;
                    renderStep(1);
                });
            }
        } else if (step === 3) {
            const input = document.getElementById('emailInput');
            const nextBtn = document.getElementById('stepNextBtn');
            const backBtn = document.getElementById('stepBackBtn');
            if (input) {
                input.addEventListener('input', function(e) {
                    state.email = e.target.value.trim();
                });
                if (state.email) input.value = state.email;
            }
            if (nextBtn) {
                nextBtn.addEventListener('click', function() {
                    const val = document.getElementById('emailInput')?.value?.trim() || '';
                    if (!val || !val.includes('@') || !val.includes('.')) {
                        setFeedback('Please enter a valid email address.', 'error');
                        return;
                    }
                    state.email = val;
                    currentStep = 4;
                    renderStep(4);
                });
                input?.addEventListener('keydown', function(e) {
                    if (e.key === 'Enter') nextBtn.click();
                });
            }
            if (backBtn) {
                backBtn.addEventListener('click', function() {
                    currentStep = 2;
                    renderStep(2);
                });
            }
        } else if (step === 4) {
            const backBtn = document.getElementById('stepBackBtn');
            const submitBtn = document.getElementById('submitBtn');
            if (backBtn) {
                backBtn.addEventListener('click', function() {
                    currentStep = 3;
                    renderStep(3);
                });
            }
            if (submitBtn) {
                submitBtn.addEventListener('click', function() {
                    handleSubmit();
                });
            }
        }
    }

    function maskToken(token) {
        if (!token) return '—';
        if (token.length <= 8) return token;
        return token.slice(0, 4) + '••••' + token.slice(-4);
    }

    async function handleSubmit() {
        const payload = {
            api_token: state.api_token,
            app_id: state.app_id,
            email: state.email,
        };

        if (!payload.api_token || !payload.app_id || !payload.email) {
            setFeedback('All fields are required.', 'error');
            return;
        }

        const submitBtn = document.getElementById('submitBtn');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-pulse"></i> Sending...';
        }

        try {
            const response = await fetch('/auth', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });

            let data;
            try {
                data = await response.json();
            } catch (_) {
                data = {};
            }

            if (response.ok) {
                setFeedback(data.detail || 'Account ready!', 'success');
                stepContainer.innerHTML = `
                    <div class="finish-message">
                        <i class="fas fa-check-circle icon-big"></i>
                        <h3>Welcome to Amy</h3>
                        <p>${data.detail || 'You\'re all set. Happy building!'}</p>
                        <div style="margin-top:2rem;">
                            <button class="btn-startover" onclick="location.reload()"><i class="fas fa-redo"></i> Start over</button>
                        </div>
                    </div>
                `;
                segments.forEach(function(s) {
                    s.classList.remove('active');
                    s.classList.add('completed');
                });
                labels.forEach(function(l) {
                    l.classList.remove('active');
                    l.classList.add('completed');
                });
            } else {
                const msg = data.detail || 'Something went wrong.';
                setFeedback(msg, 'error');
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = '<i class="fas fa-check"></i> Finish';
                }
            }
        } catch (err) {
            setFeedback('Network error. Please try again.', 'error');
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-check"></i> Finish';
            }
        }
    }

    renderStep(1);
})();