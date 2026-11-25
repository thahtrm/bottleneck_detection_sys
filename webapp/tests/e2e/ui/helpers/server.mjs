import fs from 'node:fs';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import { spawn, spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const E2E_ROOT = path.resolve(__dirname, '..', '..');
const WEBAPP_DIR = path.resolve(E2E_ROOT, '..', '..');
const REPO_ROOT = path.resolve(WEBAPP_DIR, '..');
const BACKEND_DIR = path.join(WEBAPP_DIR, 'backend');
const SRC_DIR = path.join(REPO_ROOT, 'src');

function resolvePythonExecutable() {
  const override = process.env.E2E_PYTHON;
  if (override && fs.existsSync(override)) {
    return override;
  }
  const venvPy = path.join(REPO_ROOT, '.venv', 'bin', 'python');
  if (fs.existsSync(venvPy)) {
    return venvPy;
  }
  return 'python3';
}

function getFreePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on('error', reject);
    server.listen(0, '127.0.0.1', () => {
      const addr = server.address();
      const port = typeof addr === 'object' && addr ? addr.port : 0;
      server.close((err) => (err ? reject(err) : resolve(port)));
    });
  });
}

async function waitForHealth(baseUrl, timeoutMs = 20_000, getLogs = () => '') {
  const deadline = Date.now() + timeoutMs;
  let lastErr = null;
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`${baseUrl}/healthz`);
      if (res.ok) {
        const body = await res.json();
        if (body && body.status === 'ok') {
          return;
        }
      }
      lastErr = new Error(`Unexpected /healthz status: ${res.status}`);
    } catch (err) {
      lastErr = err;
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  const logs = getLogs();
  throw new Error(
    `Timed out waiting for ${baseUrl}/healthz (${lastErr?.message || 'unknown error'}).` +
      (logs ? `\nServer output:\n${logs}` : ''),
  );
}

export async function startIsolatedServer({
  richNetwork = true,
  seed = true,
  jiraMode = 'local',
  jiraBaseUrl = jiraMode === 'local' ? '' : 'https://example.atlassian.net',
} = {}) {
  const externalBase = process.env.E2E_BASE_URL?.trim();
  if (externalBase) {
    const baseUrl = externalBase.replace(/\/$/, '');
    await waitForHealth(baseUrl, 20_000);
    return {
      baseUrl,
      external: true,
      tmpDir: null,
      stop: async () => {},
    };
  }

  const distIndex = path.join(WEBAPP_DIR, 'frontend', 'dist', 'index.html');
  if (!fs.existsSync(distIndex)) {
    throw new Error(
      `Built frontend not found at ${distIndex}. Run 'npm --prefix webapp/frontend run build' or set E2E_BASE_URL.`,
    );
  }

  const port = await getFreePort();
  const baseUrl = `http://127.0.0.1:${port}`;
  const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'erw-ui-e2e-'));
  for (const sub of ['attachments', 'reports', 'rag/seed', 'stream']) {
    fs.mkdirSync(path.join(tmpDir, sub), { recursive: true });
  }

  const pythonExe = resolvePythonExecutable();
  const env = {
    ...process.env,
    PYTHONDONTWRITEBYTECODE: '1',
    PYTHONPATH: `${BACKEND_DIR}${path.delimiter}${SRC_DIR}`,
    DB_URL: `sqlite:///${path.join(tmpDir, 'erw.db')}`,
    JIRA_MODE: jiraMode,
    JIRA_BASE_URL: jiraBaseUrl,
    JIRA_EMAIL: '',
    JIRA_API_TOKEN: '',
    JIRA_PROJECTS: 'DEMO',
    OLLAMA_URL: '',
    SLACK_WEBHOOK_URL: '',
    ATTACHMENTS_DIR: path.join(tmpDir, 'attachments'),
    REPORTS_DIR: path.join(tmpDir, 'reports'),
    RAG_SEED_DIR: path.join(tmpDir, 'rag', 'seed'),
    RAG_INDEX_PATH: path.join(tmpDir, 'rag', 'faiss.index'),
    BASE_DUCKDB: path.join(tmpDir, 'missing_base.duckdb'),
    WORK_DUCKDB: path.join(tmpDir, 'work.duckdb'),
    STREAM_DIR: path.join(tmpDir, 'stream'),
    BUNDLES_DIR: path.join(REPO_ROOT, 'bundles'),
    EMB_DIR: path.join(REPO_ROOT, 'data'),
    SESSION_SECRET: 'e2e-test-session-secret',
    WEB_BASE_URL: baseUrl,
  };

  if (seed) {
    const seedArgs = ['-m', 'erw.cli', 'seed-demo', '--reset'];
    if (richNetwork) {
      seedArgs.push('--rich-network');
    }
    const seedRes = spawnSync(pythonExe, seedArgs, {
      cwd: tmpDir,
      env,
      encoding: 'utf8',
    });
    if (seedRes.status !== 0) {
      fs.rmSync(tmpDir, { recursive: true, force: true });
      throw new Error(
        `seed-demo failed (exit ${seedRes.status}):\n${seedRes.stdout || ''}\n${seedRes.stderr || ''}`,
      );
    }
  }

  const pyBoot = [
    'import uvicorn',
    'from erw.main import create_app',
    'app = create_app(catch_up_on_startup=False, start_scheduler_on_startup=False)',
    `uvicorn.run(app, host='127.0.0.1', port=${port}, log_level='warning')`,
  ].join('; ');

  const logs = [];
  const child = spawn(pythonExe, ['-c', pyBoot], {
    cwd: tmpDir,
    env,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout?.on('data', (chunk) => logs.push(chunk.toString()));
  child.stderr?.on('data', (chunk) => logs.push(chunk.toString()));

  const stop = async () => {
    if (child.exitCode === null && !child.killed) {
      child.kill('SIGTERM');
      await new Promise((resolve) => {
        const timer = setTimeout(() => {
          if (child.exitCode === null) {
            child.kill('SIGKILL');
          }
          resolve();
        }, 5000);
        child.once('exit', () => {
          clearTimeout(timer);
          resolve();
        });
      });
    }
    fs.rmSync(tmpDir, { recursive: true, force: true });
  };

  try {
    await waitForHealth(baseUrl, 20_000, () => logs.join(''));
  } catch (err) {
    await stop();
    throw err;
  }

  return {
    baseUrl,
    external: false,
    tmpDir,
    stop,
  };
}
