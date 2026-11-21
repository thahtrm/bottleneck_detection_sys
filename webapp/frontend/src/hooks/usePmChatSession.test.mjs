import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const here = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(here, 'usePmChatSession.js'), 'utf8');

test('chat session keeps a project-keyed draft map for bubble ↔ tab remounts', () => {
  assert.match(source, /draftByProject/);
  assert.match(source, /queryKey:\s*\['chat-messages',\s*project\]/);
  assert.match(source, /refetchInterval/);
});
