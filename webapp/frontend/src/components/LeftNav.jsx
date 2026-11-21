import React from 'react';
import { ActionIcon, Stack, Tooltip } from '@mantine/core';
import {
  IconAdjustments,
  IconAffiliate,
  IconLayoutKanban,
  IconLayoutSidebarLeftCollapse,
  IconLayoutSidebarLeftExpand,
  IconList,
  IconMessageCircle,
  IconSettings,
  IconUsers,
} from '@tabler/icons-react';
import '../styles/kaggleTokens.css';
import AppLogo from './brand/AppLogo';

const NAV_META = [
  { value: 'board', label: 'Bảng', Icon: IconLayoutKanban },
  { value: 'list', label: 'Danh sách', Icon: IconList },
  { value: 'graph', label: 'Đồ thị', Icon: IconAffiliate },
  { value: 'chat', label: 'Chat', Icon: IconMessageCircle, chatOnly: true },
  { value: 'users', label: 'Người dùng', Icon: IconUsers, adminOnly: true },
  { value: 'project-settings', label: 'Cài đặt dự án', Icon: IconAdjustments, projectOnly: true },
  { value: 'settings', label: 'Cài đặt', Icon: IconSettings },
];

export function buildViewNavItems({ showChatNav, showUsersNav, showProjectSettingsNav }) {
  return NAV_META.filter((item) => {
    if (item.chatOnly && !showChatNav) return false;
    if (item.adminOnly && !showUsersNav) return false;
    if (item.projectOnly && !showProjectSettingsNav) return false;
    return true;
  });
}

/**
 * Left vertical view rail (under AppShell header).
 * Desktop: 220px expanded / 64px collapsed with tooltips.
 * Mobile drawer always shows labels (caller passes collapsed=false).
 */
export default function LeftNav({
  view,
  onViewChange,
  showChatNav = false,
  showUsersNav = false,
  showProjectSettingsNav = false,
  collapsed = false,
  onToggleCollapsed,
  showCollapseToggle = false,
}) {
  const items = buildViewNavItems({ showChatNav, showUsersNav, showProjectSettingsNav });
  const active = items.some((item) => item.value === view) ? view : 'board';
  const scopeClass = collapsed ? 'erw-nav-scope erw-nav-collapsed' : 'erw-nav-scope';

  return (
    <nav className={scopeClass} aria-label="Điều hướng chính">
      <div className="erw-nav-brand">
        {collapsed ? <AppLogo variant="mark" size="sm" /> : <AppLogo variant="mark" size="sm" showTitle />}
      </div>
      <Stack gap="xs" className="erw-nav-stack">
        {items.map(({ value, label, Icon }) => {
          const isActive = value === active;
          const button = (
            <button
              type="button"
              className="erw-nav-item"
              data-active={isActive ? 'true' : 'false'}
              aria-current={isActive ? 'page' : undefined}
              aria-label={label}
              onClick={() => onViewChange && onViewChange(value)}
            >
              <Icon size={20} stroke={1.75} className="erw-nav-icon" aria-hidden />
              <span className="erw-nav-label">{label}</span>
            </button>
          );

          if (!collapsed) return <React.Fragment key={value}>{button}</React.Fragment>;

          return (
            <Tooltip key={value} label={label} position="right" withArrow openDelay={200}>
              {button}
            </Tooltip>
          );
        })}
      </Stack>

      {showCollapseToggle && onToggleCollapsed ? (
        <div className="erw-nav-footer">
          <Tooltip
            label={collapsed ? 'Mở rộng thanh điều hướng' : 'Thu gọn thanh điều hướng'}
            position="right"
            withArrow
          >
            <ActionIcon
              className="erw-nav-collapse-btn"
              variant="subtle"
              size="lg"
              radius="xl"
              aria-label={collapsed ? 'Mở rộng thanh điều hướng' : 'Thu gọn thanh điều hướng'}
              aria-pressed={collapsed}
              onClick={() => onToggleCollapsed(!collapsed)}
            >
              {collapsed ? (
                <IconLayoutSidebarLeftExpand size={20} stroke={1.75} />
              ) : (
                <IconLayoutSidebarLeftCollapse size={20} stroke={1.75} />
              )}
            </ActionIcon>
          </Tooltip>
        </div>
      ) : null}
    </nav>
  );
}
