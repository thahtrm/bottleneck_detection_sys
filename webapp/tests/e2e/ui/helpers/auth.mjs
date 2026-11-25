export const ROLE_CREDENTIALS = {
  admin: {
    email: 'admin@earlyrisk.local',
    password: 'Admin@123456',
    role: 'admin',
  },
  pm: {
    email: 'pm@earlyrisk.local',
    password: 'Pm@123456',
    role: 'pm',
  },
  viewer: {
    email: 'viewer@earlyrisk.local',
    password: 'Viewer@123456',
    role: 'viewer',
  },
  developer: {
    email: 'an@earlyrisk.local',
    password: 'Dev@123456',
    role: 'developer',
  },
};

function escapeRegExp(str) {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function findDemoUserForRole(users, roleOrEmail, fallbackEmail) {
  if (!Array.isArray(users)) {
    return null;
  }
  const normalized = roleOrEmail.toLowerCase();
  const isKnownRole = Object.prototype.hasOwnProperty.call(ROLE_CREDENTIALS, normalized);
  const emailCandidates = [normalized, fallbackEmail?.toLowerCase()].filter(Boolean);

  // 1. Exact email match
  const byEmail = users.find((u) => u.email && emailCandidates.includes(u.email.toLowerCase()));
  if (byEmail) {
    return byEmail;
  }

  // 2. Role match via DemoUserItem schema (is_admin / projects[].role), preferring non-admin for project roles
  if (isKnownRole) {
    const bySchemaRole = users.find(
      (u) =>
        (normalized === 'admin' && u.is_admin) ||
        (normalized !== 'admin' &&
          !u.is_admin &&
          Array.isArray(u.projects) &&
          u.projects.some((p) => p.role === normalized)),
    );
    if (bySchemaRole) {
      return bySchemaRole;
    }
  }

  // 3. Fallback: general projects[].role, legacy u.role / u.project_role, or email substring
  return (
    users.find(
      (u) =>
        (normalized === 'admin' && u.is_admin) ||
        (Array.isArray(u.projects) && u.projects.some((p) => p.role === normalized)) ||
        u.role === normalized ||
        u.project_role === normalized ||
        (isKnownRole &&
          u.email &&
          u.email.toLowerCase().includes(normalized === 'developer' ? 'dev' : normalized)),
    ) || null
  );
}

export async function ensureRoleCredentials(baseUrl, role) {
  const fallback = ROLE_CREDENTIALS[role];
  if (!fallback) {
    throw new Error(`Unknown E2E role: ${role}`);
  }
  try {
    const res = await fetch(`${baseUrl}/api/demo/users`);
    if (res.ok) {
      const users = await res.json();
      const match = findDemoUserForRole(users, role, fallback.email);
      if (match) {
        return {
          ...fallback,
          id: match.id,
          name: match.name || fallback.name,
          email: match.email || fallback.email,
        };
      }
    }
  } catch {
    // Endpoint may not exist prior to M1; use standard fallback credentials.
  }
  return fallback;
}

export async function loginViaForm(page, baseUrl, creds = ROLE_CREDENTIALS.admin) {
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Địa chỉ Email').fill(creds.email);
  await page.locator('input[type="password"]').fill(creds.password);
  await page.getByRole('button', { name: 'Đăng nhập' }).click();
  await page.locator('nav[aria-label="Điều hướng chính"]').waitFor({ state: 'visible' });
}

export async function loginViaApi(page, baseUrl, creds = ROLE_CREDENTIALS.pm) {
  const res = await page.request.post(`${baseUrl}/api/auth/login`, {
    data: { email: creds.email, password: creds.password },
  });
  if (!res.ok()) {
    const text = await res.text();
    throw new Error(`API login failed for ${creds.email}: ${res.status()} ${text}`);
  }
  await page.goto(baseUrl, { waitUntil: 'domcontentloaded' });
  await page.locator('nav[aria-label="Điều hướng chính"]').waitFor({ state: 'visible' });
  return res.json();
}

export async function quickSwitchUser(page, baseUrl, roleOrEmail) {
  const normalized = roleOrEmail.toLowerCase();
  const creds = ROLE_CREDENTIALS[normalized] || { email: roleOrEmail, password: null };

  // Resolve target DemoUserItem (including name/email/projects[].role) before matching UI options
  let targetUser = null;
  try {
    const listRes = await page.request.get(`${baseUrl}/api/demo/users`);
    if (listRes.ok()) {
      const users = await listRes.json();
      targetUser = findDemoUserForRole(users, roleOrEmail, creds.email);
    }
  } catch {
    // Ignore and fall back to creds below
  }

  const resolvedEmail = targetUser?.email || creds.email;
  const resolvedName = targetUser?.name || null;

  // Prefer M4 UI Quick Switch selector if present in Header
  const uiSwitcher = page.getByLabel(/Quick Switch|Chuyển tài khoản/i);
  if ((await uiSwitcher.count()) > 0 && (await uiSwitcher.first().isVisible())) {
    await uiSwitcher.first().click();
    const candidates = [resolvedName, resolvedEmail, resolvedEmail?.split('@')[0]].filter(Boolean);
    for (const label of candidates) {
      const option = page.getByRole('option', {
        name: new RegExp(escapeRegExp(label), 'i'),
      });
      if ((await option.count()) > 0) {
        await option.first().click();
        await page.waitForLoadState('networkidle');
        return;
      }
    }
  }

  // Fallback to API quick-switch if M1 endpoint exists
  if (targetUser?.id != null) {
    try {
      const sw = await page.request.post(`${baseUrl}/api/auth/quick-switch`, {
        data: { user_id: targetUser.id },
      });
      if (sw.ok()) {
        await page.reload({ waitUntil: 'domcontentloaded' });
        await page.locator('nav[aria-label="Điều hướng chính"]').waitFor({ state: 'visible' });
        return sw.json();
      }
    } catch {
      // Fall back to explicit loginViaApi below
    }
  }

  if (!creds.password) {
    throw new Error(`Cannot switch to ${roleOrEmail}: quick-switch unavailable and no password known.`);
  }
  return loginViaApi(page, baseUrl, { ...creds, email: resolvedEmail });
}

export async function logoutViaUi(page) {
  const byRole = page.getByRole('button', { name: /Đăng xuất/i });
  const byIcon = page.locator('header button').filter({ has: page.locator('svg.tabler-icon-logout') });
  const logoutBtn = byRole.or(byIcon).first();
  await logoutBtn.waitFor({ state: 'visible' });
  await logoutBtn.click();
  await page.getByRole('button', { name: 'Đăng nhập' }).waitFor({ state: 'visible' });
}
