/**
 * AURORA - Core UI Logic
 * Supabase-backed search, filter, pagination, and live features
 */

// ─── Pagination Engine ─────────────────────────────────────────
const PER_PAGE = 10;

function renderPagination(containerId, currentPage, totalPages, onPageChange) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = '';

    if (totalPages <= 1) {
        const btn = document.createElement('button');
        btn.className = 'page-btn active';
        btn.textContent = '1';
        el.appendChild(btn);
        return;
    }

    // Prev
    const prevBtn = document.createElement('button');
    prevBtn.className = 'page-btn';
    prevBtn.textContent = '‹';
    prevBtn.disabled = currentPage <= 1;
    if (currentPage > 1) prevBtn.onclick = () => onPageChange(currentPage - 1);
    if (currentPage <= 1) prevBtn.style.opacity = '0.4';
    el.appendChild(prevBtn);

    // Page numbers
    const pages = getPageNumbers(currentPage, totalPages);
    pages.forEach(p => {
        const btn = document.createElement('button');
        btn.className = 'page-btn' + (p === currentPage ? ' active' : '');
        if (p === '...') {
            btn.textContent = '...';
            btn.disabled = true;
            btn.style.cursor = 'default';
        } else {
            btn.textContent = p;
            btn.onclick = () => onPageChange(p);
        }
        el.appendChild(btn);
    });

    // Next
    const nextBtn = document.createElement('button');
    nextBtn.className = 'page-btn';
    nextBtn.textContent = '›';
    nextBtn.disabled = currentPage >= totalPages;
    if (currentPage < totalPages) nextBtn.onclick = () => onPageChange(currentPage + 1);
    if (currentPage >= totalPages) nextBtn.style.opacity = '0.4';
    el.appendChild(nextBtn);
}

function getPageNumbers(current, total) {
    if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
    const pages = [];
    pages.push(1);
    if (current > 3) pages.push('...');
    for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
        pages.push(i);
    }
    if (current < total - 2) pages.push('...');
    pages.push(total);
    return pages;
}

function updateFooterInfo(elementId, start, end, total) {
    const el = document.getElementById(elementId);
    if (!el) return;
    if (total === 0) {
        el.innerHTML = 'Showing <strong>0</strong> entries';
    } else {
        el.innerHTML = `Showing <strong>${start}-${end}</strong> of <strong>${total.toLocaleString()}</strong> entries`;
    }
}

function showEmptyState(tbody, cols, message) {
    tbody.innerHTML = `<tr><td colspan="${cols}" style="text-align: center; padding: 32px; color: var(--text-secondary, #a0aec0); font-style: italic;">${message}</td></tr>`;
}

function showLoadingState(tbody, cols) {
    tbody.innerHTML = `<tr><td colspan="${cols}" style="text-align: center; padding: 32px; color: var(--text-secondary, #a0aec0);"><i class="fas fa-spinner fa-spin"></i> Loading...</td></tr>`;
}

// ─── Dashboard (index.html) ────────────────────────────────────
async function initDashboard() {
    const searchInput = document.getElementById('searchStudent');
    const statusFilter = document.getElementById('dashboardStatusFilter');
    const tbody = document.getElementById('attendanceTableBody');
    if (!tbody) return;

    let currentPage = 1;

    async function loadDashboard() {
        // Show loading
        showLoadingState(tbody, 3);

        const filters = {
            search: searchInput?.value || '',
            status: statusFilter?.value || 'All Status',
            limit: PER_PAGE,
            offset: (currentPage - 1) * PER_PAGE
        };

        const { data, count } = await fetchTodayAttendance(filters);

        // Render table
        if (data.length === 0) {
            showEmptyState(tbody, 3, 'No attendance records found');
        } else {
            tbody.innerHTML = '';
            data.forEach(record => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${record.name || '--'}</td>
                    <td>${formatTime(record.time)}</td>
                    <td>${statusBadge(record.status)}</td>
                `;
                tbody.appendChild(row);
            });
        }

        // Pagination
        const totalPages = Math.max(1, Math.ceil(count / PER_PAGE));
        renderPagination('dashPagination', currentPage, totalPages, (page) => {
            currentPage = page;
            loadDashboard();
        });
        const start = data.length > 0 ? (currentPage - 1) * PER_PAGE + 1 : 0;
        const end = start + data.length - (data.length > 0 ? 1 : 0);
        updateFooterInfo('dashFooterInfo', start, start + data.length - 1, count);
    }

    // Load stats
    async function loadStats() {
        const stats = await fetchStats();

        const presentEl = document.querySelector('.stat-card.present .number');
        const absentEl = document.querySelector('.stat-card.absent .number');
        const lateEl = document.querySelector('.stat-card.late .number');

        if (presentEl) presentEl.textContent = stats.present.toLocaleString();
        if (absentEl) absentEl.textContent = stats.absent.toLocaleString();
        if (lateEl) lateEl.textContent = stats.late.toLocaleString();

        // Update percentages
        const total = stats.total_registered || 1;
        const presentPct = document.querySelector('.stat-card.present .percentage');
        const absentPct = document.querySelector('.stat-card.absent .percentage');
        const latePct = document.querySelector('.stat-card.late .percentage');

        if (presentPct) presentPct.innerHTML = `<i class="fas fa-arrow-up"></i> ${Math.round((stats.present / total) * 100)}%`;
        if (absentPct) absentPct.innerHTML = `<i class="fas fa-arrow-down"></i> ${Math.round((stats.absent / total) * 100)}%`;
        if (latePct) latePct.innerHTML = `<i class="fas fa-arrow-down"></i> ${Math.round((stats.late / total) * 100)}%`;
    }

    // Event listeners
    let searchTimeout;
    searchInput?.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => { currentPage = 1; loadDashboard(); }, 300);
    });
    statusFilter?.addEventListener('change', () => { currentPage = 1; loadDashboard(); });

    // Initial load
    await Promise.all([loadStats(), loadDashboard()]);

    // Real-time updates
    subscribeAttendance((eventType, record) => {
        if (eventType === 'INSERT') {
            console.log('[Realtime] New attendance:', record.name);
            loadStats();
            loadDashboard();
        }
    });
}

// ─── Attendance (attendance.html) ──────────────────────────────
async function initAttendance() {
    const searchInput = document.getElementById('searchAttendance');
    const tbody = document.getElementById('attendanceHistoryBody');
    if (!tbody) return;

    let currentPage = 1;

    async function loadAttendance() {
        showLoadingState(tbody, 5);

        const statusSel = document.getElementById('statusFilter');
        const dateRangeSel = document.getElementById('dateRangeSelect');
        const dateFrom = document.getElementById('dateFrom');
        const dateTo = document.getElementById('dateTo');

        const filters = {
            search: searchInput?.value || '',
            status: statusSel?.value || 'All Status',
            limit: PER_PAGE,
            offset: (currentPage - 1) * PER_PAGE
        };

        // Date range logic
        const dateRange = dateRangeSel?.value || 'all';
        const now = new Date();
        const offset = 7 * 60;
        const local = new Date(now.getTime() + (offset + now.getTimezoneOffset()) * 60000);

        if (dateRange === 'all') {
            // No date filter — show all records
        } else if (dateRange === 'today') {
            const todayStr = local.getFullYear() + '-' +
                String(local.getMonth() + 1).padStart(2, '0') + '-' +
                String(local.getDate()).padStart(2, '0');
            filters.date = todayStr;
        } else if (dateRange === 'week') {
            const weekStart = new Date(local);
            weekStart.setDate(local.getDate() - local.getDay());
            filters.dateFrom = weekStart.getFullYear() + '-' +
                String(weekStart.getMonth() + 1).padStart(2, '0') + '-' +
                String(weekStart.getDate()).padStart(2, '0');
        } else if (dateRange === 'month') {
            const monthStart = local.getFullYear() + '-' +
                String(local.getMonth() + 1).padStart(2, '0') + '-01';
            filters.dateFrom = monthStart;
        } else if (dateRange === 'custom') {
            if (dateFrom?.value) filters.dateFrom = dateFrom.value;
            if (dateTo?.value) filters.dateTo = dateTo.value;
        }

        const { data, count } = await fetchAttendance(filters);

        // Render table
        if (data.length === 0) {
            showEmptyState(tbody, 5, 'No attendance records found');
        } else {
            tbody.innerHTML = '';
            data.forEach(record => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${formatDate(record.date)}</td>
                    <td>${record.name || '--'}</td>
                    <td>${formatTime(record.time)}</td>
                    <td>--:-- --</td>
                    <td>${statusBadge(record.status)}</td>
                `;
                tbody.appendChild(row);
            });
        }

        // Pagination
        const totalPages = Math.max(1, Math.ceil(count / PER_PAGE));
        renderPagination('attPagination', currentPage, totalPages, (page) => {
            currentPage = page;
            loadAttendance();
        });
        updateFooterInfo('attFooterInfo',
            data.length > 0 ? (currentPage - 1) * PER_PAGE + 1 : 0,
            (currentPage - 1) * PER_PAGE + data.length,
            count
        );
    }

    // Load attendance stat cards (all-time totals for this page)
    async function loadAttendanceStats() {
        const stats = await fetchAllTimeStats();

        const presentEl = document.querySelector('.stat-card.present .number');
        const lateEl = document.querySelector('.stat-card.late .number');
        // Note: absent card intentionally left as "N/A" — all-time absent is not tracked

        if (presentEl) presentEl.textContent = stats.present.toLocaleString();
        if (lateEl) lateEl.textContent = stats.late.toLocaleString();
    }

    // Event listeners
    let searchTimeout;
    searchInput?.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => { currentPage = 1; loadAttendance(); }, 300);
    });

    // Override applyFilters for the Apply button
    window.applyFilters = () => { currentPage = 1; loadAttendance(); };

    // Initial load
    await Promise.all([loadAttendanceStats(), loadAttendance()]);

    // Real-time updates
    subscribeAttendance((eventType) => {
        if (eventType === 'INSERT') {
            loadAttendanceStats();
            loadAttendance();
        }
    });
}

// ─── Registered Faces (registered.html) ────────────────────────
async function initRegistered() {
    const searchInput = document.getElementById('searchFaces');
    const tbody = document.getElementById('facesTableBody');
    if (!tbody) return;

    let currentPage = 1;

    async function loadFaces() {
        showLoadingState(tbody, 2);

        const filters = {
            search: searchInput?.value || '',
            limit: PER_PAGE,
            offset: (currentPage - 1) * PER_PAGE
        };

        const { data, count } = await fetchFaces(filters);

        // Update total count card
        const totalEl = document.querySelector('.info-value');
        if (totalEl) totalEl.textContent = count.toLocaleString();

        // Render table
        if (data.length === 0) {
            showEmptyState(tbody, 2, 'No registered faces found');
        } else {
            tbody.innerHTML = '';
            data.forEach(face => {
                const row = document.createElement('tr');
                row.innerHTML = `
                    <td>${face.name || '--'}</td>
                    <td>${formatDate(face.created_at?.split('T')[0])}</td>
                `;
                tbody.appendChild(row);
            });
        }

        // Pagination
        const totalPages = Math.max(1, Math.ceil(count / PER_PAGE));
        renderPagination('regPagination', currentPage, totalPages, (page) => {
            currentPage = page;
            loadFaces();
        });
        updateFooterInfo('regFooterInfo',
            data.length > 0 ? (currentPage - 1) * PER_PAGE + 1 : 0,
            (currentPage - 1) * PER_PAGE + data.length,
            count
        );
    }

    // Search
    let searchTimeout;
    searchInput?.addEventListener('input', () => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => { currentPage = 1; loadFaces(); }, 300);
    });

    // Initial load
    await loadFaces();

    // Real-time updates
    subscribeFaces(() => { loadFaces(); });
}

// ─── Register Modal (registered.html) ──────────────────────────
function openRegisterModal() {
    // Remove existing modal if any
    const existing = document.getElementById('registerModal');
    if (existing) existing.remove();

    const modal = document.createElement('div');
    modal.id = 'registerModal';
    modal.style.cssText = `
        position:fixed;top:0;left:0;width:100%;height:100%;
        background:rgba(0,0,0,0.6);display:flex;align-items:center;
        justify-content:center;z-index:1000;backdrop-filter:blur(4px);
    `;
    modal.innerHTML = `
        <div style="background:var(--card-bg,#1e1e2e);border-radius:16px;padding:32px;
            width:420px;max-width:90%;box-shadow:0 20px 60px rgba(0,0,0,0.4);">
            <h3 style="margin:0 0 20px;color:var(--text-primary,#fff);">
                <i class="fas fa-user-plus" style="margin-right:8px;color:#48bb78;"></i>
                Register New Face
            </h3>
            <form id="registerForm" style="display:flex;flex-direction:column;gap:14px;">
                <input type="text" name="name" required placeholder="Full Name"
                    style="padding:10px 14px;border-radius:8px;border:1px solid rgba(255,255,255,0.1);
                    background:rgba(255,255,255,0.05);color:var(--text-primary,#fff);font-size:14px;">
                <input type="text" name="class" placeholder="Class (e.g. XII-A)"
                    style="padding:10px 14px;border-radius:8px;border:1px solid rgba(255,255,255,0.1);
                    background:rgba(255,255,255,0.05);color:var(--text-primary,#fff);font-size:14px;">
                <input type="file" name="image" accept="image/*" required
                    style="padding:10px;border-radius:8px;border:1px solid rgba(255,255,255,0.1);
                    background:rgba(255,255,255,0.05);color:var(--text-primary,#fff);font-size:13px;">
                <div style="display:flex;gap:10px;margin-top:8px;">
                    <button type="submit" class="btn-primary"
                        style="flex:1;padding:10px;border:none;border-radius:8px;cursor:pointer;">
                        <i class="fas fa-check"></i> Register
                    </button>
                    <button type="button" onclick="document.getElementById('registerModal').remove()"
                        style="flex:1;padding:10px;border-radius:8px;cursor:pointer;
                        background:rgba(255,255,255,0.1);color:var(--text-primary,#fff);border:none;">
                        Cancel
                    </button>
                </div>
                <div id="registerStatus" style="font-size:13px;text-align:center;min-height:20px;"></div>
            </form>
        </div>
    `;
    document.body.appendChild(modal);

    // Close on backdrop click
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.remove();
    });

    // Handle form submit
    document.getElementById('registerForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const form = e.target;
        const statusEl = document.getElementById('registerStatus');
        statusEl.textContent = 'Registering...';
        statusEl.style.color = '#a0aec0';

        try {
            const formData = new FormData(form);
            const resp = await fetch(`${SERVER_URL}/api/register`, {
                method: 'POST',
                body: formData
            });
            const result = await resp.json();

            if (resp.ok) {
                statusEl.textContent = '✅ ' + (result.message || 'Registered successfully!');
                statusEl.style.color = '#48bb78';
                setTimeout(() => modal.remove(), 1500);
            } else {
                statusEl.textContent = '❌ ' + (result.detail || 'Registration failed');
                statusEl.style.color = '#fc8181';
            }
        } catch (err) {
            statusEl.textContent = '❌ Server error: ' + err.message;
            statusEl.style.color = '#fc8181';
        }
    });
}

// ─── Live Feed (live-feed.html) ────────────────────────────────────────
async function initLiveFeed() {
    // Fullscreen button
    const fullscreenBtn = document.getElementById('fullscreenBtn');
    const videoContainer = document.getElementById('videoContainer');

    if (fullscreenBtn && videoContainer) {
        fullscreenBtn.addEventListener('click', function () {
            if (videoContainer.requestFullscreen) {
                videoContainer.requestFullscreen();
            } else if (videoContainer.webkitRequestFullscreen) {
                videoContainer.webkitRequestFullscreen();
            } else if (videoContainer.msRequestFullscreen) {
                videoContainer.msRequestFullscreen();
            }
        });
    }

    // Clock
    const timeEl = document.getElementById('currentTime');
    if (timeEl) {
        setInterval(() => {
            timeEl.textContent = new Date().toLocaleTimeString('en-US');
        }, 1000);
        timeEl.textContent = new Date().toLocaleTimeString('en-US');
    }

    // Load activity history from Supabase + start WebSocket
    connectAnnotatedFeed();
}

function connectAnnotatedFeed() {
    const feedImg = document.getElementById('cameraFeed');
    const scanStatus = document.getElementById('scanStatus');
    const liveIndicator = document.getElementById('liveIndicator');
    const fpsDisplay = document.getElementById('fpsDisplay');
    const connectionStatus = document.getElementById('connectionStatus');
    const cameraDetails = document.getElementById('cameraDetails');

    // Sensor cards
    const espStatus = document.getElementById('espStatus');
    const espIcon = document.getElementById('espIcon');
    const distanceEl = document.getElementById('ultrasonicDistance');
    const distanceStatus = document.getElementById('distanceStatus');
    const recentNameEl = document.getElementById('recentDetectionName');
    const recentInfoEl = document.getElementById('recentDetectionInfo');

    // Live stream table
    const streamBody = document.getElementById('liveStreamBody');

    // --- Activity History: Supabase pagination ---
    let streamPage = 1;

    async function loadActivityHistory() {
        if (!streamBody) return;

        showLoadingState(streamBody, 4);

        const { data, count } = await fetchActivityLogs({
            limit: PER_PAGE,
            offset: (streamPage - 1) * PER_PAGE
        });

        if (data.length === 0) {
            showEmptyState(streamBody, 4, 'No activity logs yet');
        } else {
            streamBody.innerHTML = '';
            data.forEach(record => {
                const row = document.createElement('tr');
                const isKnown = record.event_type === 'KNOWN';
                const timeStr = record.timestamp
                    ? new Date(record.timestamp).toLocaleTimeString('en-US')
                    : '--';
                const conf = record.confidence
                    ? `${(record.confidence * 100).toFixed(0)}%`
                    : '--';
                const eventLabel = isKnown ? 'Face Recognized' : 'Face Detected';

                if (isKnown) {
                    row.innerHTML = `
                        <td>${timeStr}</td>
                        <td>${eventLabel}</td>
                        <td><strong>${record.name || 'Unknown'}</strong></td>
                        <td><span class="badge present">${conf}</span></td>
                    `;
                } else {
                    row.innerHTML = `
                        <td>${timeStr}</td>
                        <td>${eventLabel}</td>
                        <td style="color: #f56565;">Unknown</td>
                        <td><span class="badge" style="background: rgba(245,101,101,0.2); color: #f56565;">${conf}</span></td>
                    `;
                }
                streamBody.appendChild(row);
            });
        }

        // Pagination controls
        const totalPages = Math.max(1, Math.ceil(count / PER_PAGE));
        renderPagination('streamPagination', streamPage, totalPages, (page) => {
            streamPage = page;
            loadActivityHistory();
        });
        updateFooterInfo('streamFooterInfo',
            data.length > 0 ? (streamPage - 1) * PER_PAGE + 1 : 0,
            (streamPage - 1) * PER_PAGE + data.length,
            count
        );
    }

    // Load history on init
    loadActivityHistory();

    // Prepend a real-time row from WebSocket (at top, visual-only until next load)
    function prependStreamRow(eventType, name, confidence, isKnown) {
        if (!streamBody) return;

        const now = new Date().toLocaleTimeString('en-US');
        const conf = confidence ? `${(confidence * 100).toFixed(0)}%` : '--';
        const row = document.createElement('tr');
        const eventLabel = isKnown ? 'Face Recognized' : 'Face Detected';

        if (isKnown) {
            row.innerHTML = `
                <td>${now}</td>
                <td>${eventLabel}</td>
                <td><strong>${name}</strong></td>
                <td><span class="badge present">${conf}</span></td>
            `;
        } else {
            row.innerHTML = `
                <td>${now}</td>
                <td>${eventLabel}</td>
                <td style="color: #f56565;">Unknown</td>
                <td><span class="badge" style="background: rgba(245,101,101,0.2); color: #f56565;">${conf}</span></td>
            `;
        }

        // Only prepend if we're on page 1
        if (streamPage === 1) {
            streamBody.insertBefore(row, streamBody.firstChild);
            // Keep max PER_PAGE + 5 rows visible (slight overflow OK)
            while (streamBody.children.length > PER_PAGE + 5) {
                streamBody.removeChild(streamBody.lastChild);
            }
        }
    }

    let ws;
    let reconnectDelay = 1000;
    let previousBlobUrl = null;

    // FPS tracking
    let frameCount = 0;
    let fpsStart = performance.now();

    setInterval(() => {
        const elapsed = (performance.now() - fpsStart) / 1000;
        if (elapsed >= 1) {
            const fps = frameCount / elapsed;
            if (fpsDisplay) fpsDisplay.textContent = `${fps.toFixed(1)} FPS`;
            frameCount = 0;
            fpsStart = performance.now();
        }
    }, 1000);

    // Auto-detect ws vs wss based on SERVER_URL
    function getWsUrl() {
        if (typeof WS_URL !== 'undefined' && WS_URL) {
            return `${WS_URL}/ws/feed/annotated`;
        }
        if (typeof SERVER_URL !== 'undefined' && SERVER_URL) {
            const wsProto = SERVER_URL.startsWith('https') ? 'wss' : 'ws';
            const host = SERVER_URL.replace(/^https?:\/\//, '');
            return `${wsProto}://${host}/ws/feed/annotated`;
        }
        const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        return `${proto}//${window.location.host}/ws/feed/annotated`;
    }

    function setConnectionState(state) {
        if (!connectionStatus) return;
        const states = {
            connecting: { bg: 'rgba(255,165,0,0.2)', color: '#ffa500', text: 'Connecting' },
            connected:  { bg: 'rgba(72,187,120,0.2)', color: '#48bb78', text: 'Connected' },
            disconnected: { bg: 'rgba(245,101,101,0.2)', color: '#f56565', text: 'Disconnected' },
        };
        const s = states[state] || states.connecting;
        connectionStatus.style.background = s.bg;
        connectionStatus.style.color = s.color;
        connectionStatus.innerHTML = `<i class="fas fa-circle" style="font-size: 8px;"></i> ${s.text}`;
    }

    function connect() {
        const wsUrl = getWsUrl();
        console.log(`[LiveFeed] Connecting to ${wsUrl}...`);
        setConnectionState('connecting');

        try {
            ws = new WebSocket(wsUrl);
            ws.binaryType = 'blob';
        } catch (e) {
            console.warn('[LiveFeed] WebSocket creation failed:', e);
            setConnectionState('disconnected');
            scheduleReconnect();
            return;
        }

        ws.onopen = () => {
            console.log('[LiveFeed] ✓ Connected to annotated feed');
            reconnectDelay = 1000;
            setConnectionState('connected');
            if (cameraDetails) cameraDetails.textContent = 'Live Stream Active';
            if (scanStatus) {
                scanStatus.textContent = 'SCAN ACTIVE';
                scanStatus.style.background = 'rgba(66, 153, 225, 0.9)';
            }
            if (liveIndicator) liveIndicator.style.opacity = '1';
        };

        ws.onmessage = (event) => {
            if (event.data instanceof Blob) {
                // Binary = annotated JPEG frame
                const newUrl = URL.createObjectURL(event.data);
                if (feedImg) feedImg.src = newUrl;

                // Revoke previous Blob URL to prevent memory leak
                if (previousBlobUrl) URL.revokeObjectURL(previousBlobUrl);
                previousBlobUrl = newUrl;

                frameCount++;

            } else if (typeof event.data === 'string') {
                try {
                    const data = JSON.parse(event.data);

                    // Overlay data (sensor + faces)
                    if (data.type === 'overlay') {
                        // Sensor data
                        if (data.sensor) {
                            const dist = data.sensor.distance_cm;
                            const online = data.sensor.esp32_online;

                            if (espStatus) espStatus.textContent = online ? '🟢 Online' : '🔴 Offline';
                            if (espIcon) espIcon.style.color = online ? '#48bb78' : '#888';
                            if (distanceEl) {
                                distanceEl.textContent = dist >= 0 ? `${dist.toFixed(1)} cm` : '-- cm';
                            }
                            if (distanceStatus) {
                                distanceStatus.innerHTML = online
                                    ? '<i class="fas fa-signal"></i> Live'
                                    : '<i class="fas fa-signal"></i> Waiting';
                            }
                        }

                        // Face data
                        const faces = data.faces || [];
                        const knownFaces = faces.filter(f => f.known);
                        const unknownFaces = faces.filter(f => !f.known);
                        const totalFaces = faces.length;

                        // --- Scan status indicator ---
                        if (scanStatus) {
                            if (knownFaces.length > 0) {
                                scanStatus.textContent = `✅ ${knownFaces.length} RECOGNIZED`;
                                scanStatus.style.background = 'rgba(72, 187, 120, 0.9)';
                            } else if (unknownFaces.length > 0) {
                                scanStatus.textContent = `⚠️ ${unknownFaces.length} UNKNOWN`;
                                scanStatus.style.background = 'rgba(245, 158, 11, 0.9)';
                            } else {
                                scanStatus.textContent = 'SCAN ACTIVE';
                                scanStatus.style.background = 'rgba(66, 153, 225, 0.9)';
                            }
                        }

                        // --- Recent Detection card (from live overlay) ---
                        if (totalFaces > 0) {
                            // Pick closest face (largest bbox area)
                            const closest = faces.reduce((best, f) => {
                                if (!f.bbox || f.bbox.length !== 4) return best;
                                const area = (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]);
                                return area > best.area ? { face: f, area } : best;
                            }, { face: faces[0], area: 0 });

                            const mainFace = closest.face;
                            const conf = mainFace.confidence
                                ? `${(mainFace.confidence * 100).toFixed(0)}%`
                                : '--';

                            let displayName = mainFace.known ? mainFace.name : 'Unknown';
                            let infoText = `${mainFace.known ? 'Matched' : 'Confidence'} ${conf}`;

                            // Show others count
                            if (totalFaces > 1) {
                                const otherNames = faces
                                    .filter(f => f !== mainFace)
                                    .map(f => f.known ? f.name : 'Unknown');
                                displayName += ` + ${totalFaces - 1} other${totalFaces > 2 ? 's' : ''}`;
                            }

                            if (recentNameEl) recentNameEl.textContent = displayName;
                            if (recentInfoEl) recentInfoEl.textContent = infoText;
                        } else {
                            if (recentNameEl) recentNameEl.textContent = 'No face detected';
                            if (recentInfoEl) recentInfoEl.textContent = 'Waiting for recognition...';
                        }

                        // --- Live Stream table: handled by activity WS events ---
                        // (No client-side cooldown — server handles it)
                    }

                    // Activity event (from server, already cooldown-filtered)
                    if (data.type === 'activity') {
                        const isKnown = data.event_type === 'KNOWN';
                        prependStreamRow(
                            data.event_type, data.name, data.confidence, isKnown
                        );
                    }

                    // Recognition event (attendance actually logged by server)
                    if (data.type === 'recognition') {
                        prependStreamRow(
                            'ATTENDANCE', data.name, data.confidence, true
                        );
                    }
                } catch (e) {
                    // Ignore parse errors
                }
            }
        };

        ws.onclose = () => {
            console.log('[LiveFeed] Disconnected, reconnecting...');
            setConnectionState('disconnected');
            if (cameraDetails) cameraDetails.textContent = 'Reconnecting...';
            if (scanStatus) {
                scanStatus.textContent = 'FEED OFFLINE';
                scanStatus.style.background = 'rgba(245, 101, 101, 0.9)';
            }
            if (liveIndicator) liveIndicator.style.opacity = '0.5';
            scheduleReconnect();
        };

        ws.onerror = (err) => {
            console.error('[LiveFeed] WebSocket error:', err);
            ws.close();
        };
    }

    function scheduleReconnect() {
        console.log(`[LiveFeed] Reconnecting in ${reconnectDelay / 1000}s...`);
        setTimeout(connect, reconnectDelay);
        reconnectDelay = Math.min(reconnectDelay * 2, 10000);
    }

    connect();
}

// ─── Auto-initialize on page load ──────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
    // Initialize Supabase
    initSupabase();

    // Detect page and init
    if (document.getElementById('attendanceTableBody') && document.getElementById('searchStudent')) {
        initDashboard();
    }
    if (document.getElementById('attendanceHistoryBody')) {
        initAttendance();
    }
    if (document.getElementById('facesTableBody')) {
        initRegistered();
    }
    if (document.getElementById('cameraFeed')) {
        initLiveFeed();
    }
});
