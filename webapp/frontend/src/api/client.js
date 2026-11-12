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
 * Lấy dữ liệu thống kê tổng quan (Dashboard stats)
 * @param {string|null} [project=null] - Key của dự án, hoặc null/rỗng để lấy tất cả
 */
export async function getDashboardStats(project = null) {
  const query = project ? `?project=${encodeURIComponent(project)}` : '';
  return await apiFetch(`/api/dashboard/stats${query}`, {
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
 * Lấy danh sách task rủi ro từ dashboard
 * @param {Object} [params={}] - Các tham số lọc (project, level, status_category, is_critical, blocked, assignee_id, q, sort_by, order, limit, offset)
 * @returns {Promise<{total: number, limit: number, offset: number, items: Array}>}
 */
export async function getDashboardIssues(params = {}) {
  const searchParams = new URLSearchParams();

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      searchParams.append(key, String(value));
    }
  });

  const queryString = searchParams.toString();
  const path = `/api/dashboard/issues${queryString ? `?${queryString}` : ''}`;
  return await apiFetch(path, {
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





