import React, { useMemo } from 'react';
import { renderMarkdown } from './reportMarkdownRender.mjs';

export { renderMarkdown };

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
