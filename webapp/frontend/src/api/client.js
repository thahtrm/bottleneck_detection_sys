/**
 * API Client for Early Risk Web
 * Uses fetch with credentials: 'include' for session cookie management.
 */

export async function apiFetch(path, options = {}) {
  const { headers = {}, body, ...restOptions } = options;

  const defaultHeaders = {};
  let processedBody = body;

  if (body !== undefined && body !== null) {
    if (
      typeof body === 'object' &&
      !(body instanceof FormData) &&
      !(body instanceof Blob) &&
      !(body instanceof URLSearchParams)
    ) {
      defaultHeaders['Content-Type'] = 'application/json';
      processedBody = JSON.stringify(body);
    } else if (typeof body === 'string') {
      defaultHeaders['Content-Type'] = 'application/json';
    }
  }

  const mergedHeaders = {
    ...defaultHeaders,
    ...headers,
  };

  const response = await fetch(path, {
    credentials: 'include',
    headers: mergedHeaders,
    body: processedBody,
    ...restOptions,
  });

  if (!response.ok) {
    let errorData = null;
    try {
      errorData = await response.json();
    } catch {
      // Body is not JSON
    }
    const detailMsg =
      errorData?.detail && typeof errorData.detail === 'object'
        ? errorData.detail.message || errorData.detail.error || JSON.stringify(errorData.detail)
        : errorData?.detail;
    const message =
      detailMsg ||
      errorData?.message ||
      `Yêu cầu thất bại với mã trạng thái ${response.status}: ${response.statusText}`;
    const error = new Error(message);
    error.status = response.status;
    error.data = errorData;
    throw error;
  }

  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    return await response.json();
  }

  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

/**
 * Đăng nhập bằng email và mật khẩu
 */
export async function login(email, password) {
  return await apiFetch('/api/auth/login', {
    method: 'POST',
    body: { email, password },
  });
}

/**
 * Đăng xuất người dùng hiện tại
 */
export async function logout() {
  return await apiFetch('/api/auth/logout', {
    method: 'POST',
  });
}

/**
 * Lấy thông tin người dùng đang đăng nhập
 */
export async function getMe() {
  return await apiFetch('/api/auth/me', {
    method: 'GET',
  });
}

/**
 * Lấy danh sách dự án
 */
export async function getProjects() {
  return await apiFetch('/api/projects', {
    method: 'GET',
  });
}

/**
 * Lấy bảng rủi ro: thẻ công việc, sprint, tiến độ và cột trạng thái Jira
 * @param {{project?: string, q?: string, sprint?: number|null}} params
 */
export async function getBoard({ project, q, sprint }) {
  const params = new URLSearchParams();
  if (project) params.set('project', project);
  if (q) params.set('q', q);
  if (sprint != null) params.set('sprint', String(sprint));
  const query = params.toString();
  return await apiFetch(`/api/dashboard/board${query ? `?${query}` : ''}`, {
    method: 'GET',
  });
}

/**
 * Lấy dữ liệu đồ thị mạng lưới phụ thuộc và điểm nghẽn
 * @param {string|null} [project=null] - Key của dự án, hoặc null/rỗng để lấy tất cả
 */
export async function getDashboardGraph(project = null) {
  const query = project ? `?project=${encodeURIComponent(project)}` : '';
  return await apiFetch(`/api/dashboard/graph${query}`, {
    method: 'GET',
  });
}

/**
 * Lấy cấu hình hệ thống và trạng thái webhook (Admin settings)
 */
export async function getAdminSettings() {
  return await apiFetch('/api/admin/settings', {
    method: 'GET',
  });
}

/**
 * Lấy chi tiết toàn diện của một công việc (issue) kèm điểm số, rủi ro, liên kết và lịch sử
 * @param {string} key - Mã issue (ví dụ: 'DEMO-1')
 */
export async function getIssueDetail(key) {
  if (!key) throw new Error('Mã công việc không được để trống');
  return await apiFetch(`/api/issues/${encodeURIComponent(key)}`, {
    method: 'GET',
  });
}

/**
 * Lấy đề xuất hành động từ AI cho công việc (có thể trả về 202 pending nếu đang phân tích)
 * @param {string} key - Mã issue
 */
export async function getIssueSuggestion(key) {
  if (!key) throw new Error('Mã công việc không được để trống');
  return await apiFetch(`/api/issues/${encodeURIComponent(key)}/suggestion`, {
    method: 'GET',
  });
}

/**
 * Lấy các chuyển trạng thái Jira hợp lệ cho công việc (chỉ PM)
 * @param {string} key - Mã issue
 * @returns {Promise<Array<{id: string, name: string, to_status: string, to_category: string}>>}
 */
export async function getIssueTransitions(key) {
  if (!key) throw new Error('Mã công việc không được để trống');
  return await apiFetch(`/api/issues/${encodeURIComponent(key)}/transitions`, {
    method: 'GET',
  });
}

/**
 * Bỏ qua cảnh báo rủi ro ở mức hiện tại của công việc (chỉ dành cho PM/Admin)
 * @param {string} key - Mã issue
 * @param {string} [reason=""] - Lý do bỏ qua (tùy chọn)
 */
export async function dismissIssueRisk(key, reason = '') {
  if (!key) throw new Error('Mã công việc không được để trống');
  return await apiFetch(`/api/issues/${encodeURIComponent(key)}/dismiss`, {
    method: 'POST',
    body: { reason },
  });
}

/**
 * Tạo một đề xuất hành động (Draft proposal) từ gợi ý LLM để chuẩn bị xác nhận
 * @param {string} issueKey - Mã issue
 * @param {number|null} [suggestionId=null] - ID của suggestion từ LLM
 * @param {Array} [items=[]] - Danh sách các action items đề xuất
 */
export async function proposeAction(issueKey, suggestionId = null, items = []) {
  if (!issueKey) throw new Error('Mã công việc không được để trống');
  return await apiFetch('/api/actions/propose', {
    method: 'POST',
    body: {
      issue_key: issueKey,
      suggestion_id: suggestionId,
      items,
    },
  });
}

/**
 * Xác nhận thực thi hành động đã đề xuất (Ghi ngược Jira)
 * @param {number|string} actionId - ID của hành động đề xuất (Action ID)
 * @param {string} expectedUpdated - Mốc thời gian updated_at dự kiến của issue trên Jira (ISO string)
 */
export async function confirmAction(actionId, expectedUpdated) {
  if (!actionId) throw new Error('ID hành động không được để trống');
  return await apiFetch(`/api/actions/${encodeURIComponent(actionId)}/confirm`, {
    method: 'POST',
    body: {
      expected_updated: expectedUpdated,
    },
  });
}

/**
 * Cập nhật cấu hình quản trị hệ thống (ngưỡng trễ hạn, ngưỡng quan trọng, LLM model)
 * @param {Object} data - { delay_threshold, criticality_top_pct, llm_model }
 */
export async function updateAdminSettings(data) {
  return await apiFetch('/api/admin/settings', {
    method: 'POST',
    body: data,
  });
}

/**
 * Kích hoạt chạy lô mô hình tính toán rủi ro ngay lập tức trong tiến trình nền
 */
export async function runModelBatch() {
  return await apiFetch('/api/admin/run-batch', {
    method: 'POST',
  });
}

/**
 * Bật/tắt trạng thái theo dõi của một dự án Jira (Admin)
 * @param {string} key - Mã dự án (Key)
 */
export async function toggleProjectTracking(key) {
  if (!key) throw new Error('Mã dự án không được để trống');
  return await apiFetch(`/api/admin/projects/${encodeURIComponent(key)}/toggle-tracking`, {
    method: 'POST',
  });
}

export async function getChatMessages(project) {
  const query = new URLSearchParams({ project });
  return await apiFetch(`/api/chat/messages?${query.toString()}`);
}

export async function postChatMessage(project, text) {
  return await apiFetch('/api/chat/messages', {
    method: 'POST',
    body: { project, text },
  });
}

export async function getChatSchedule() {
  return await apiFetch('/api/chat/schedule');
}

export async function putChatSchedule(times) {
  return await apiFetch('/api/chat/schedule', {
    method: 'PUT',
    body: times,
  });
}

export async function getChatMemories(project) {
  const query = new URLSearchParams({ project });
  return await apiFetch(`/api/chat/memories?${query.toString()}`);
}

export async function postChatMemory(project, kind, text, metadata = {}) {
  return await apiFetch('/api/chat/memories', {
    method: 'POST',
    body: { project, kind, text, metadata },
  });
}

export async function patchChatMemory(project, memoryId, patch) {
  const query = new URLSearchParams({ project });
  return await apiFetch(`/api/chat/memories/${encodeURIComponent(memoryId)}?${query.toString()}`, {
    method: 'PATCH',
    body: patch,
  });
}

export async function deleteChatMemory(project, memoryId) {
  const query = new URLSearchParams({ project });
  return await apiFetch(`/api/chat/memories/${encodeURIComponent(memoryId)}?${query.toString()}`, {
    method: 'DELETE',
  });
}

/** List non-hidden health report artifacts for project members. */
export async function getChatReports(project) {
  const query = new URLSearchParams({ project });
  return await apiFetch(`/api/chat/reports?${query.toString()}`);
}

/** Stream report from disk (`format`: md | pdf). */
export async function downloadChatReport(reportId, format = 'md') {
  const query = new URLSearchParams({ format });
  const response = await fetch(
    `/api/chat/reports/${encodeURIComponent(reportId)}/download?${query.toString()}`,
    { credentials: 'include' },
  );
  if (!response.ok) {
    const error = new Error(`Tải báo cáo thất bại (${response.status})`);
    error.status = response.status;
    throw error;
  }
  const blob = await response.blob();
  const disposition = response.headers.get('content-disposition') || '';
  const match = disposition.match(/filename\*?=(?:UTF-8''|")?([^\";]+)"?/i);
  const fallbackExt = format === 'pdf' ? 'pdf' : 'md';
  const filename = match?.[1]
    ? decodeURIComponent(match[1])
    : `report-${reportId}.${fallbackExt}`;
  return { blob, filename };
}

/** On-demand Daily Project Health Report (PM/Admin). */
export async function generateHealthReport(project) {
  return await apiFetch(`/api/projects/${encodeURIComponent(project)}/health-report`, {
    method: 'POST',
  });
}

/** Soft-hide report from file manager (timeline message kept). */
export async function hideChatReport(reportId) {
  return await apiFetch(`/api/chat/reports/${encodeURIComponent(reportId)}/hide`, {
    method: 'POST',
  });
}

/** User chat surface prefs — `{ bubble_enabled }` (default true). */
export async function getChatPrefs() {
  return await apiFetch('/api/chat/prefs');
}

export async function putChatPrefs(prefs) {
  return await apiFetch('/api/chat/prefs', {
    method: 'PUT',
    body: prefs,
  });
}

/** Read-only LLM / Ollama / RAG / Slack flags for Settings. */
export async function getChatSystemStatus() {
  return await apiFetch('/api/chat/system-status');
}

/** Admin: list app users (optional `q` search). */
export async function listAdminUsers(q = '') {
  const query = new URLSearchParams();
  if (q) query.set('q', q);
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return await apiFetch(`/api/admin/users${suffix}`);
}

/** Admin: create user; response includes one-time `generated_password`. */
export async function createAdminUser({ email, name, is_admin = false }) {
  return await apiFetch('/api/admin/users', {
    method: 'POST',
    body: { email, name, is_admin },
  });
}

/** Admin: patch user; pass `reset_password: true` for one-time generated password. */
export async function patchAdminUser(userId, patch) {
  return await apiFetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: patch,
  });
}

export async function listProjectMembers(projectKey) {
  return await apiFetch(`/api/projects/${encodeURIComponent(projectKey)}/members`);
}

export async function addProjectMember(projectKey, { email, role = 'viewer' }) {
  return await apiFetch(`/api/projects/${encodeURIComponent(projectKey)}/members`, {
    method: 'POST',
    body: { email, role },
  });
}

export async function patchProjectMember(projectKey, userId, { role }) {
  return await apiFetch(
    `/api/projects/${encodeURIComponent(projectKey)}/members/${encodeURIComponent(userId)}`,
    {
      method: 'PATCH',
      body: { role },
    },
  );
}

export async function removeProjectMember(projectKey, userId) {
  return await apiFetch(
    `/api/projects/${encodeURIComponent(projectKey)}/members/${encodeURIComponent(userId)}`,
    {
      method: 'DELETE',
    },
  );
}

