import { useCallback, useState } from 'react';

const STORAGE_KEY = 'erw-nav-collapsed';

function readStored() {
  try {
    return localStorage.getItem(STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

/**
 * Desktop left-rail collapse (§7.2 B). Persists in localStorage.
 * true = 64px icon-only; false = 220px expanded.
 */
export function useNavCollapsed() {
  const [collapsed, setCollapsedState] = useState(readStored);

  const setCollapsed = useCallback((next) => {
    setCollapsedState((prev) => {
      const value = Boolean(typeof next === 'function' ? next(prev) : next);
      try {
        localStorage.setItem(STORAGE_KEY, value ? '1' : '0');
      } catch {
        /* ignore quota / private mode */
      }
      return value;
    });
  }, []);

  return [collapsed, setCollapsed];
}
