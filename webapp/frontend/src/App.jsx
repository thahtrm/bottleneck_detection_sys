import React, { useState } from 'react';
import { AppShell, Box, Center, Loader, ScrollArea, Stack, Text } from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './context/AuthContext';
import { getProjects } from './api/client';
import { useDashboardState } from './dashboard/urlState.js';
import { useBubblePref } from './hooks/useBubblePref';
import { useNavCollapsed } from './hooks/useNavCollapsed';
import Login from './pages/Login';
import Settings from './pages/Settings';
import ProjectSettings from './pages/ProjectSettings';
import Reports from './pages/Reports';
import UsersAdmin from './pages/UsersAdmin';
import Header from './components/Header';
import LeftNav from './components/LeftNav';
import BoardView from './components/board/BoardView';
import IssuePanel from './components/IssuePanel';
import ActionConfirmModal from './components/ActionConfirmModal';
import NetworkGraph from './components/NetworkGraph';
import OverviewPage from './components/overview/OverviewPage';
import PmChatBubbleShell from './components/chat/PmChatBubbleShell';
import PmChatPage from './components/chat/PmChatPage';

const NAV_EXPANDED_WIDTH = 220;
const NAV_COLLAPSED_WIDTH = 64;

const ACTION_QUERY_KEYS = [['dashboard-board'], ['dashboard-graph'], ['issue-detail'], ['issue-suggestion']];
const REFRESH_QUERY_KEYS = [
  ['dashboard-board'],
  ['dashboard-graph'],
  ['project-overview'],
  ['projects'],
  ['admin-settings'],
];

function moveStatusProposal(card) {
  return {
    issueKey: card.key,
    issue: { updated_at: card.updated_at, summary: card.summary },
    suggestion: {
      actions: [{ action_type: 'change_status', target: '', value: '', reason: 'PM chuyển trạng thái từ bảng' }],
    },
    suggestionId: null,
  };
}

function AppContent() {
  const { user, loading } = useAuth();
  const queryClient = useQueryClient();
  const [state, patch] = useDashboardState();
  const [bubbleEnabled] = useBubblePref(Boolean(user));
  const [navCollapsed, setNavCollapsed] = useNavCollapsed();
  const [mobileNavOpened, setMobileNavOpened] = useState(false);
  const isMobileNav = useMediaQuery('(max-width: 61.99em)');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [confirmModalData, setConfirmModalData] = useState(null);
  const [confirmModalOpened, setConfirmModalOpened] = useState(false);
  const [suggestionKey, setSuggestionKey] = useState(null);
  const [suggestionNonce, setSuggestionNonce] = useState(0);
  // Only apply desktop collapse after media query resolves (avoid flash on mobile).
  const railCollapsed = Boolean(navCollapsed) && isMobileNav === false;
  const navbarWidth = railCollapsed ? NAV_COLLAPSED_WIDTH : NAV_EXPANDED_WIDTH;

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: getProjects,
    enabled: Boolean(user),
    staleTime: 30000,
  });

  const invalidate = (keys) => Promise.all(keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })));

  const handleOpenConfirmAction = (proposalData) => {
    setConfirmModalData(proposalData);
    setConfirmModalOpened(true);
  };

  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await invalidate(REFRESH_QUERY_KEYS);
    } finally {
      setIsRefreshing(false);
    }
  };

  if (loading) {
    return (
      <Center h="100vh">
        <Stack align="center" gap="sm">
          <Loader size="lg" type="dots" />
          <Text c="dimmed" size="sm">
            Đang tải dữ liệu...
          </Text>
        </Stack>
      </Center>
    );
  }

  if (!user) {
    return <Login />;
  }

  const canUseChat = user.is_admin || projects.some((item) => item.role === 'pm');
  const pmProjects = new Set(projects.filter((p) => p.role === 'pm').map((p) => p.key));
  const canMoveStatus = (card) => user.is_admin || pmProjects.has(card.project_key);
  const selectedProjectRole = projects.find((item) => item.key === state.project)?.role;
  // API require_chat_access: admin or PM on the selected project (not merely "is PM somewhere").
  const canChatOnSelected =
    Boolean(state.project) && (user.is_admin || selectedProjectRole === 'pm');
  // §8.1 A+B / §8.4 A: Báo cáo nav for members who can read project reports.
  const canReadReportsOnSelected =
    Boolean(state.project) &&
    (user.is_admin || selectedProjectRole === 'pm' || selectedProjectRole === 'viewer');
  const showReportsNav =
    Boolean(state.project) &&
    (user.is_admin ||
      projects.some((item) => item.key === state.project && (item.role === 'pm' || item.role === 'viewer')));

  // Settings open to all authenticated; chat nav for PM/Admin only; users nav admin-only.
  // Project-settings stays selectable without project (empty state); nav item requires project.
  // Landing default is overview (§8.3-A); forbidden views fall back there too.
  let view = state.view;
  if (view === 'chat' && !canUseChat) view = 'overview';
  if (view === 'reports' && !canReadReportsOnSelected) view = 'overview';
  if (view === 'users' && !user.is_admin) view = 'overview';

  const selectIssue = (issue) => {
    setSuggestionKey(null);
    patch({ issue });
  };

  /** Bubble on Board/List: open IssuePanel on current view. */
  const openFromBubble = (key) => {
    setSuggestionKey(key);
    setSuggestionNonce((nonce) => nonce + 1);
    patch({ issue: key });
  };

  /** Chat tab: navigate Board + open IssuePanel. */
  const openFromChatTab = (key) => {
    setSuggestionKey(key);
    setSuggestionNonce((nonce) => nonce + 1);
    patch({ view: 'board', issue: key });
  };

  // FAB hidden on overview (and Graph/Chat/Settings) — §2.1.
  const showBubble = bubbleEnabled && (view === 'board' || view === 'list') && canUseChat;
  const boardLike = view === 'board' || view === 'list';
  // Chat tab must fill the viewport like Board/List so the page never scrolls;
  // message history scrolls inside PmChatTimeline instead.
  const fillViewport = boardLike || view === 'chat' || view === 'overview';
  // Overview owns its Explain drawer; do not open IssuePanel there.
  const panelOpen =
    Boolean(state.issue) &&
    view !== 'overview' &&
    view !== 'settings' &&
    view !== 'project-settings' &&
    view !== 'chat' &&
    view !== 'reports' &&
    view !== 'users';

  return (
    <AppShell
      header={{ height: 60 }}
      navbar={{
        width: navbarWidth,
        breakpoint: 'md',
        collapsed: { mobile: !mobileNavOpened, desktop: false },
      }}
      aside={{ width: 440, breakpoint: 'sm', collapsed: { desktop: !panelOpen, mobile: !panelOpen } }}
      padding="md"
      styles={{
        main: fillViewport
          ? {
              display: 'flex',
              flexDirection: 'column',
              overflow: 'hidden',
              height: 'calc(100dvh - var(--app-shell-header-offset, 60px))',
              boxSizing: 'border-box',
            }
          : undefined,
      }}
    >
      <AppShell.Header>
        <Header
          projects={projects}
          selectedProject={state.project}
          onSelectProject={(project) => patch({ project })}
          searchQuery={state.q}
          onSearchChange={(q) => patch({ q })}
          onRefresh={handleRefresh}
          isRefreshing={isRefreshing}
          mobileNavOpened={mobileNavOpened}
          onToggleMobileNav={() => setMobileNavOpened((open) => !open)}
        />
      </AppShell.Header>

      <AppShell.Navbar p={0}>
        <LeftNav
          view={view}
          onViewChange={(next) => {
            patch({ view: next });
            setMobileNavOpened(false);
          }}
          showChatNav={canUseChat}
          showUsersNav={Boolean(user.is_admin)}
          showProjectSettingsNav={Boolean(state.project)}
          showReportsNav={showReportsNav}
          collapsed={railCollapsed}
          onToggleCollapsed={setNavCollapsed}
          showCollapseToggle={!isMobileNav}
        />
      </AppShell.Navbar>

      {panelOpen && (
        <AppShell.Aside>
          <AppShell.Section grow component={ScrollArea} p="sm">
            <IssuePanel
              key={state.issue}
              issueKey={state.issue}
              onClose={() => selectIssue(null)}
              onOpenConfirmAction={handleOpenConfirmAction}
              projects={projects}
              onSelectIssue={selectIssue}
              suggestionNonce={suggestionKey === state.issue ? suggestionNonce : 0}
            />
          </AppShell.Section>
        </AppShell.Aside>
      )}

      <AppShell.Main>
        {view === 'settings' && (
          <Settings
            project={state.project}
            projects={projects}
            onBackToDashboard={() => patch({ view: 'overview' })}
            onOpenChat={() => patch({ view: 'chat' })}
            onOpenReports={
              state.project ? () => patch({ view: 'reports' }) : undefined
            }
            onOpenUsers={user.is_admin ? () => patch({ view: 'users' }) : undefined}
            onOpenProjectSettings={
              state.project ? () => patch({ view: 'project-settings' }) : undefined
            }
          />
        )}
        {view === 'project-settings' && (
          <ProjectSettings
            project={state.project}
            projects={projects}
            onOpenSystemSettings={() => patch({ view: 'settings' })}
            onOpenReports={() => patch({ view: 'reports' })}
            onOpenChat={canUseChat ? () => patch({ view: 'chat' }) : undefined}
          />
        )}
        {view === 'overview' && (
          <Box style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            <OverviewPage
              project={state.project}
              selectedIssueKey={state.issue}
              onSelectIssue={selectIssue}
              onOpenBoard={(key) => patch({ view: 'board', issue: key })}
            />
          </Box>
        )}
        {view === 'reports' && (
          <Reports
            project={state.project}
            projects={projects}
            selectedReportId={state.report}
            onSelectReport={(report) => patch({ report })}
            onOpenChat={canUseChat ? () => patch({ view: 'chat' }) : undefined}
            onAskReportInChat={
              canUseChat
                ? (reportId) => patch({ view: 'chat', report: reportId })
                : undefined
            }
            onOpenProjectSettings={() => patch({ view: 'project-settings' })}
            onOpenScheduleSettings={() => patch({ view: 'settings' })}
          />
        )}
        {view === 'users' && <UsersAdmin />}
        {view === 'graph' && (
          <NetworkGraph selectedProject={state.project} onSelectIssue={selectIssue} selectedIssueKey={state.issue} />
        )}
        {view === 'chat' && (
          <Box style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            <PmChatPage
              project={state.project}
              canChatOnProject={canChatOnSelected}
              onOpenIssue={openFromChatTab}
              onOpenSettings={() => patch({ view: 'settings' })}
              initialAttachReportId={state.report}
            />
          </Box>
        )}
        {boardLike && (
          <Box style={{ flex: 1, minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column' }}>
            <BoardView
              state={state}
              patch={patch}
              canMoveStatus={canMoveStatus}
              onMoveStatus={(card) => handleOpenConfirmAction(moveStatusProposal(card))}
              onSelectIssue={selectIssue}
            />
          </Box>
        )}

        {showBubble && (
          <PmChatBubbleShell
            project={state.project}
            canChatOnProject={canChatOnSelected}
            onOpenIssue={openFromBubble}
            onOpenSettings={() => patch({ view: 'settings' })}
            onOpenChatTab={() => patch({ view: 'chat' })}
          />
        )}

        <ActionConfirmModal
          opened={confirmModalOpened}
          onClose={() => setConfirmModalOpened(false)}
          proposalData={confirmModalData}
          onSuccess={() => invalidate(ACTION_QUERY_KEYS)}
        />
      </AppShell.Main>
    </AppShell>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppContent />
    </AuthProvider>
  );
}
