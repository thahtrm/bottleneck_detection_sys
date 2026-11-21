import assert from 'node:assert/strict';
import test from 'node:test';
import { pinChatToLatest, splitChatText } from './pmChatText.js';

test('issue keys and slack labels become issue tokens', () => {
  const parts = splitChatText('[Tăng rủi ro] <https://example/browse/DEMO-41|DEMO-41> đang chặn DEMO-18');
  assert.deepEqual(
    parts.filter((part) => part.type === 'issue').map((part) => part.key),
    ['DEMO-41', 'DEMO-18'],
  );
});

test('plain text stays text', () => {
  assert.deepEqual(splitChatText('Chưa có trong hệ thống.'), [{ type: 'text', text: 'Chưa có trong hệ thống.' }]);
});

test('pinChatToLatest moves the viewport to the newest row', () => {
  const viewport = { scrollTop: 0, scrollHeight: 900 };
  pinChatToLatest(viewport);
  assert.equal(viewport.scrollTop, 900);
});

test('pinChatToLatest ignores a missing viewport', () => {
  pinChatToLatest(null);
});
