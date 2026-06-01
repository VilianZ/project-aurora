/**
 * AURORA - Supabase Client (with Server API Fallback)
 * 
 * When Supabase is configured → queries Supabase directly for real-time data.
 * When Supabase is NOT configured → falls back to local server API endpoints.
 * 
 * IMPORTANT: The CDN UMD build exposes a global `supabase` object.
 * We use `supabaseClient` to avoid shadowing that global.
 */

// Runtime configuration.
// Copy config.example.js to config.js or run python setup.py from the repo root.
const AURORA_CONFIG = window.AURORA_CONFIG || {};
const SUPABASE_URL = AURORA_CONFIG.SUPABASE_URL || '';
const SUPABASE_ANON_KEY = AURORA_CONFIG.SUPABASE_KEY || '';

// Server URL configuration
const _isLocal = window.location.hostname === 'localhost'
    || window.location.hostname === '127.0.0.1'
    || window.location.protocol === 'file:';
const SERVER_URL = AURORA_CONFIG.SERVER_URL || (_isLocal
    ? 'http://localhost:8000'
    : window.location.origin);
const WS_URL = AURORA_CONFIG.WS_BASE || SERVER_URL.replace(/^http/, 'ws');

// Supabase client instance
let supabaseClient = null;
let _useServerFallback = false;

function initSupabase() {
    try {
        if (!SUPABASE_URL || !SUPABASE_ANON_KEY) {
            console.warn('[AURORA] Supabase not configured — using server API fallback.');
            _useServerFallback = true;
            return false;
        }
        const { createClient } = supabase;
        supabaseClient = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
        console.log('[Supabase] Client initialized');
        return true;
    } catch (e) {
        console.error('[Supabase] Failed to initialize:', e);
        console.warn('[AURORA] Falling back to server API.');
        _useServerFallback = true;
        return false;
    }
}

// --- SERVER API FALLBACK HELPERS ---

async function _serverGet(endpoint, params = {}) {
    try {
        const url = new URL(endpoint, SERVER_URL);
        for (const [k, v] of Object.entries(params)) {
            if (v !== undefined && v !== null && v !== '') {
                url.searchParams.set(k, v);
            }
        }
        const resp = await fetch(url.toString());
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        return await resp.json();
    } catch (e) {
        console.error(`[Server API] ${endpoint} failed:`, e);
        return null;
    }
}

// --- ATTENDANCE QUERIES ---

async function fetchAttendance(filters = {}) {
    // Server API fallback
    if (_useServerFallback) {
        const params = {};
        if (filters.date) params.date = filters.date;
        if (filters.search) params.search = filters.search;
        if (filters.status && filters.status.toLowerCase() !== 'all status') {
            params.status = filters.status;
        }
        const result = await _serverGet('/api/attendance', params);
        if (!result) return { data: [], count: 0 };
        return { data: result.data || [], count: result.count || 0 };
    }

    // Supabase path
    if (!supabaseClient) return { data: [], count: 0 };

    try {
        let query = supabaseClient
            .from('attendance')
            .select('*', { count: 'exact' });

        if (filters.date) query = query.eq('date', filters.date);
        if (filters.dateFrom) query = query.gte('date', filters.dateFrom);
        if (filters.dateTo) query = query.lte('date', filters.dateTo);
        if (filters.status && filters.status.toLowerCase() !== 'all status') {
            query = query.eq('status', filters.status.toLowerCase());
        }
        if (filters.search) query = query.ilike('name', `%${filters.search}%`);

        query = query.order('date', { ascending: false })
                     .order('time', { ascending: false });

        if (filters.limit) {
            const offset = filters.offset || 0;
            query = query.range(offset, offset + filters.limit - 1);
        }

        const { data, count, error } = await query;
        if (error) throw error;
        return { data: data || [], count: count || 0 };
    } catch (e) {
        console.error('[Supabase] Attendance query failed:', e);
        return { data: [], count: 0 };
    }
}

async function fetchActivityLogs(filters = {}) {
    if (_useServerFallback) {
        // Activity logs come from real-time WebSocket, not stored locally
        return { data: [], count: 0 };
    }
    if (!supabaseClient) return { data: [], count: 0 };

    try {
        let query = supabaseClient
            .from('activity_logs')
            .select('*', { count: 'exact' })
            .order('timestamp', { ascending: false });

        const limit = filters.limit || 10;
        const offset = filters.offset || 0;
        query = query.range(offset, offset + limit - 1);

        const { data, count, error } = await query;
        if (error) throw error;
        return { data: data || [], count: count || 0 };
    } catch (e) {
        console.error('[Supabase] Activity logs query failed:', e);
        return { data: [], count: 0 };
    }
}

async function fetchTodayAttendance(filters = {}) {
    const now = new Date();
    const offset = 7 * 60; // UTC+7
    const local = new Date(now.getTime() + (offset + now.getTimezoneOffset()) * 60000);
    const dateStr = local.getFullYear() + '-' +
        String(local.getMonth() + 1).padStart(2, '0') + '-' +
        String(local.getDate()).padStart(2, '0');

    return fetchAttendance({ ...filters, date: dateStr });
}

async function fetchStats() {
    // Server API fallback
    if (_useServerFallback) {
        const result = await _serverGet('/api/stats');
        if (!result) return { present: 0, late: 0, absent: 0, total_registered: 0 };
        return result;
    }

    if (!supabaseClient) return { present: 0, late: 0, absent: 0, total_registered: 0 };

    try {
        const now = new Date();
        const offset = 7 * 60;
        const local = new Date(now.getTime() + (offset + now.getTimezoneOffset()) * 60000);
        const dateStr = local.getFullYear() + '-' +
            String(local.getMonth() + 1).padStart(2, '0') + '-' +
            String(local.getDate()).padStart(2, '0');

        const { data: records } = await supabaseClient
            .from('attendance')
            .select('status')
            .eq('date', dateStr);

        const { count: totalFaces } = await supabaseClient
            .from('faces')
            .select('*', { count: 'exact', head: true });

        const present = (records || []).filter(r => r.status === 'present').length;
        const late = (records || []).filter(r => r.status === 'late').length;
        const totalRegistered = totalFaces || 0;
        const absent = Math.max(0, totalRegistered - present - late);

        return { present, late, absent, total_registered: totalRegistered };
    } catch (e) {
        console.error('[Supabase] Stats query failed:', e);
        return { present: 0, late: 0, absent: 0, total_registered: 0 };
    }
}

async function fetchAllTimeStats() {
    if (_useServerFallback) {
        const result = await _serverGet('/api/attendance');
        if (!result || !result.data) return { present: 0, late: 0, absent: 0 };
        const present = result.data.filter(r => r.status === 'present').length;
        const late = result.data.filter(r => r.status === 'late').length;
        return { present, late, absent: 0 };
    }

    if (!supabaseClient) return { present: 0, late: 0, absent: 0 };

    try {
        const { count: present } = await supabaseClient
            .from('attendance')
            .select('*', { count: 'exact', head: true })
            .eq('status', 'present');

        const { count: late } = await supabaseClient
            .from('attendance')
            .select('*', { count: 'exact', head: true })
            .eq('status', 'late');

        return { present: present || 0, late: late || 0, absent: 0 };
    } catch (e) {
        console.error('[Supabase] All-time stats query failed:', e);
        return { present: 0, late: 0, absent: 0 };
    }
}

// --- FACES QUERIES ---

async function fetchFaces(filters = {}) {
    // Server API fallback
    if (_useServerFallback) {
        const params = {};
        if (filters.search) params.search = filters.search;
        const result = await _serverGet('/api/faces', params);
        if (!result) return { data: [], count: 0 };
        return { data: result.data || [], count: result.count || 0 };
    }

    if (!supabaseClient) return { data: [], count: 0 };

    try {
        let query = supabaseClient
            .from('faces')
            .select('*', { count: 'exact' });

        if (filters.search) query = query.ilike('name', `%${filters.search}%`);
        query = query.order('created_at', { ascending: false });

        if (filters.limit) {
            const offset = filters.offset || 0;
            query = query.range(offset, offset + filters.limit - 1);
        }

        const { data, count, error } = await query;
        if (error) throw error;
        return { data: data || [], count: count || 0 };
    } catch (e) {
        console.error('[Supabase] Faces query failed:', e);
        return { data: [], count: 0 };
    }
}

// --- REALTIME SUBSCRIPTIONS ---

function subscribeAttendance(callback) {
    if (!supabaseClient) return null;

    const channel = supabaseClient
        .channel('attendance-changes')
        .on('postgres_changes',
            { event: '*', schema: 'public', table: 'attendance' },
            (payload) => { callback(payload.eventType, payload.new); }
        )
        .subscribe();

    console.log('[Supabase] Subscribed to attendance realtime');
    return channel;
}

function subscribeFaces(callback) {
    if (!supabaseClient) return null;

    const channel = supabaseClient
        .channel('faces-changes')
        .on('postgres_changes',
            { event: '*', schema: 'public', table: 'faces' },
            (payload) => { callback(payload.eventType, payload.new); }
        )
        .subscribe();

    console.log('[Supabase] Subscribed to faces realtime');
    return channel;
}

// --- UTILITY ---

function formatDate(dateStr) {
    if (!dateStr) return '--';
    const d = new Date(dateStr + 'T00:00:00');
    if (isNaN(d.getTime())) return dateStr;
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
        'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return `${months[d.getMonth()]} ${d.getDate()}, ${d.getFullYear()}`;
}

function formatTime(timeStr) {
    if (!timeStr || timeStr === '--') return '--:-- --';
    const parts = timeStr.split(':');
    const hour = parseInt(parts[0]);
    const min = parts[1] || '00';
    const ampm = hour >= 12 ? 'PM' : 'AM';
    const displayHour = hour === 0 ? 12 : hour > 12 ? hour - 12 : hour;
    return `${String(displayHour).padStart(2, '0')}:${min} ${ampm}`;
}

function statusBadge(status) {
    const s = (status || 'unknown').toLowerCase();
    return `<span class="badge ${s}">${s.charAt(0).toUpperCase() + s.slice(1)}</span>`;
}
