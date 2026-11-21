import assert from 'node:assert/strict';
import { describe, it } from 'node:test';
import { renderMarkdown } from './reportMarkdownRender.mjs';

describe('renderMarkdown indent', () => {
  it('nests group bullets inside parent li', () => {
    const md = [
      '## 2. Today’s progress',
      '### Facts',
      '- Created 24h: 0',
      '- **Created**',
      '  - (không có)',
      '- **Resolved**',
      '  - (không có)',
      '',
    ].join('\n');
    const html = renderMarkdown(md);
    assert.match(html, /<li class="erw-fact-group"><strong>Created<\/strong>\s*<ul class="erw-fact-list-nested">/);
    assert.match(html, /<li>\(không có\)\s*<\/li>/);
    assert.doesNotMatch(html, /<\/li>\s*<ul class="erw-fact-list-nested">/);
  });

  it('maps legacy Created: labels into fact groups', () => {
    const md = [
      '## 2. Today’s progress',
      '### Facts',
      '- Created 24h: 0',
      'Created:',
      '- (không có)',
      '',
    ].join('\n');
    const html = renderMarkdown(md);
    assert.match(html, /erw-fact-group/);
    assert.match(html, /Created/);
    assert.doesNotMatch(html, /<p class="erw-report-para">Created:<\/p>/);
    assert.match(html, /erw-fact-group-label">Created<\/span>\s*<ul class="erw-fact-list-nested">/);
  });

  it('closes numbered sections', () => {
    const md = ['## 1. Overview', '### Facts', '- A', '## 2. Today’s progress', '### Facts', '- B'].join('\n');
    const html = renderMarkdown(md);
    const opens = (html.match(/<section /g) || []).length;
    const closes = (html.match(/<\/section>/g) || []).length;
    assert.equal(opens, closes);
  });
});
