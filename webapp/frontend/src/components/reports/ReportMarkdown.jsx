import React, { useMemo } from 'react';

/** Escape then lightly format health-report markdown (no extra deps). */
function renderMarkdown(md) {
  const escape = (s) =>
    String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
  const lines = String(md || '').split('\n');
  const html = [];
  let inList = false;
  const closeList = () => {
    if (inList) {
      html.push('</ul>');
      inList = false;
    }
  };
  for (const raw of lines) {
    const line = raw;
    if (line.startsWith('# ')) {
      closeList();
      html.push(`<h1>${escape(line.slice(2))}</h1>`);
    } else if (line.startsWith('## ')) {
      closeList();
      html.push(`<h2>${escape(line.slice(3))}</h2>`);
    } else if (line.startsWith('### ')) {
      closeList();
      html.push(`<h3>${escape(line.slice(4))}</h3>`);
    } else if (line.startsWith('> ')) {
      closeList();
      html.push(`<p><em>${escape(line.slice(2))}</em></p>`);
    } else if (line.startsWith('- ')) {
      if (!inList) {
        html.push('<ul>');
        inList = true;
      }
      const item = escape(line.slice(2)).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      html.push(`<li>${item}</li>`);
    } else if (!line.trim()) {
      closeList();
    } else {
      closeList();
      const item = escape(line).replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      html.push(`<p>${item}</p>`);
    }
  }
  closeList();
  return html.join('\n');
}

export default function ReportMarkdown({ markdown }) {
  const html = useMemo(() => renderMarkdown(markdown), [markdown]);
  return (
    <div
      className="erw-report-md"
      // Content is escaped before insert; only our tag wrappers are raw.
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
