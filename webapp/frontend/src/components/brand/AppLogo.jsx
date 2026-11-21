import React from 'react';
import './AppLogo.css';

const MARK_SRC = '/brand/erw-mark.svg';
const WORDMARK_SRC = '/brand/erw-wordmark.svg';

/**
 * Early Risk Web brand mark / wordmark.
 * @param {'mark' | 'wordmark'} [variant='mark']
 * @param {'sm' | 'md' | 'lg' | 'xl'} [size='md']
 */
export default function AppLogo({
  variant = 'mark',
  size = 'md',
  title = 'Early Risk Web',
  className = '',
  showTitle = false,
}) {
  const isWordmark = variant === 'wordmark';
  const src = isWordmark ? WORDMARK_SRC : MARK_SRC;
  const classes = ['erw-logo', `erw-logo--${size}`, isWordmark ? 'erw-logo--wordmark' : 'erw-logo--mark', className]
    .filter(Boolean)
    .join(' ');

  return (
    <span className={classes} title={title} aria-label={title}>
      <img src={src} alt="" draggable={false} className="erw-logo__img" />
      {showTitle && !isWordmark ? (
        <span className="erw-logo__text">
          <span className="erw-logo__name">Early Risk</span>
          <span className="erw-logo__tag">Web</span>
        </span>
      ) : null}
    </span>
  );
}
