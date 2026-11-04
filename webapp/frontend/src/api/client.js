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
    const message =
      errorData?.detail ||
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
