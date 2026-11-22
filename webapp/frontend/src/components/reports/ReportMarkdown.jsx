import React, { useMemo } from 'react';

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function decorateInline(escaped) {
  return escaped
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/`\[([A-Z_]+)\]`/g, '<span class="erw-badge erw-badge-$1">[$1]</span>')
    .replace(/`([A-Z_]+)`/g, '<span class="erw-badge erw-badge-$1">$1</span>');
}

/** Hero lines: **Overall status:** / **Sprint:** — always emit explicit <strong> labels. */
function renderStatusOrSprintLine(line) {
  const overall = line.match(/^\*\*Overall status:\*\*\s*(.*)$/i);
  if (overall) {
    const rest = decorateInline(escapeHtml(overall[1] || ''));
    return `<p class="erw-report-status"><strong>Overall status:</strong> ${rest}</p>`;
  }
  const sprint = line.match(/^\*\*Sprint:\*\*\s*(.*)$/i);
  if (sprint) {
    const rest = decorateInline(escapeHtml(sprint[1] || ''));
    return `<p class="erw-report-status"><strong>Sprint:</strong> ${rest}</p>`;
  }
  // Tolerant: label without markdown markers still bolded.
  const plainOverall = line.match(/^Overall status:\s*(.*)$/i);
  if (plainOverall) {
    const rest = decorateInline(escapeHtml(plainOverall[1] || ''));
    return `<p class="erw-report-status"><strong>Overall status:</strong> ${rest}</p>`;
  }
  const plainSprint = line.match(/^Sprint:\s*(.*)$/i);
  if (plainSprint) {
    const rest = decorateInline(escapeHtml(plainSprint[1] || ''));
    return `<p class="erw-report-status"><strong>Sprint:</strong> ${rest}</p>`;
  }
  return null;
}

/** Escape then format modern health-report markdown (KPI table, badges, AI insights). */
function renderMarkdown(md) {
  const lines = String(md || '').split('\n');
  const html = [];
  let inList = false;
  let inTable = false;
  let inInsight = false;
  const closeList = () => {
    if (inList) {
      html.push('</ul>');
      inList = false;
    }
  };
  const closeTable = () => {
    if (inTable) {
      html.push('</tbody></table></div>');
      inTable = false;
    }
  };
  const closeInsight = () => {
    if (inInsight) {
      html.push('</div>');
      inInsight = false;
    }
  };

  for (const raw of lines) {
    const line = raw;
    if (line.startsWith('|') && line.includes('|')) {
      closeList();
      closeInsight();
      const cells = line
        .replace(/^\|/, '')
        .replace(/\|$/, '')
        .split('|')
        .map((c) => c.trim());
      if (cells.every((c) => /^:?-+:?$/.test(c))) {
        continue;
      }
      if (!inTable) {
        html.push('<div class="erw-kpi-wrap"><table class="erw-kpi-table"><thead><tr>');
        cells.forEach((c) => html.push(`<th>${escapeHtml(c)}</th>`));
        html.push('</tr></thead><tbody>');
        inTable = true;
      } else {
        html.push('<tr>');
        cells.forEach((c) => html.push(`<td>${decorateInline(escapeHtml(c))}</td>`));
        html.push('</tr>');
      }
      continue;
    }
    closeTable();

    if (line.startsWith('# ')) {
      closeList();
      closeInsight();
      html.push(`<div class="erw-report-hero"><div class="erw-report-kicker">Daily Project Health</div>`);
      html.push(`<h1>${escapeHtml(line.slice(2))}</h1>`);
    } else if (line.startsWith('## ') && /^\d+\./.test(line.slice(3).trim())) {
      closeList();
      closeInsight();
      if (html.includes('erw-report-hero') && !html.includes('<!--hero-end-->')) {
        html.push('<!--hero-end--></div>');
      }
      const title = line.slice(3).trim();
      const match = title.match(/^(\d+)\.\s*(.*)$/);
      const num = match?.[1] || '';
      const rest = match?.[2] || title;
      html.push(
        `<section class="erw-report-section"><div class="erw-section-head">` +
          `<span class="erw-section-num">${escapeHtml(num)}</span>` +
          `<h2>${escapeHtml(rest)}</h2></div>`,
      );
    } else if (line.startsWith('## ')) {
      closeList();
      closeInsight();
      html.push(`<h2 class="erw-report-subtitle">${escapeHtml(line.slice(3))}</h2>`);
    } else if (line.startsWith('### AI Insight')) {
      closeList();
      closeInsight();
      html.push('<div class="erw-ai-insight"><div class="erw-ai-label">AI Insight</div>');
      inInsight = true;
    } else if (line.startsWith('### ')) {
      closeList();
      closeInsight();
      html.push(`<h3>${escapeHtml(line.slice(4))}</h3>`);
    } else if (line.startsWith('> ')) {
      closeList();
      const inner = decorateInline(escapeHtml(line.slice(2)));
      if (inInsight) {
        html.push(`<p>${inner}</p>`);
      } else {
        html.push(`<p class="erw-report-meta"><em>${inner}</em></p></div>`);
      }
    } else if (line.startsWith('- ')) {
      closeInsight();
      if (!inList) {
        html.push('<ul>');
        inList = true;
      }
      html.push(`<li>${decorateInline(escapeHtml(line.slice(2)))}</li>`);
    } else if (line.trim() === '---') {
      closeList();
      closeInsight();
      html.push('<hr class="erw-report-rule" />');
    } else if (!line.trim()) {
      closeList();
      closeInsight();
    } else {
      closeList();
      const statusHtml = !inInsight ? renderStatusOrSprintLine(line.trim()) : null;
      if (statusHtml) {
        html.push(statusHtml);
      } else {
        const inner = decorateInline(escapeHtml(line));
        html.push(`<p>${inner}</p>`);
      }
    }
  }
  closeList();
  closeTable();
  closeInsight();
  // Close any open section tags roughly by counting — sections self-close via next section.
  return html.join('\n').replaceAll('</div>\n<section', '</div></section>\n<section') + '</section>'.repeat(0);
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
