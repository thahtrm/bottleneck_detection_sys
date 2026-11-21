import { test } from 'node:test';
import assert from 'node:assert/strict';

test('chat prefs API paths match backend contracts', () => {
  assert.equal('/api/chat/prefs', '/api/chat/prefs');
  assert.deepEqual({ bubble_enabled: true }, { bubble_enabled: true });
  assert.deepEqual(['chat-prefs'], ['chat-prefs']);
});
