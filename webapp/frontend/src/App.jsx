import React, { useState } from 'react';
import { AppShell, Center, Loader, ScrollArea, Stack, Text } from '@mantine/core';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './context/AuthContext';
import { getProjects } from './api/client';
import { useDashboardState } from './dashboard/urlState.js';
import Login from './pages/Login';
import Settings from './pages/Settings';
import Header from './components/Header';
import BoardView from './components/board/BoardView';
import IssuePanel from './components/IssuePanel';
import ActionConfirmModal from './components/ActionConfirmModal';
import NetworkGraph from './components/NetworkGraph';

const ACTION_QUERY_KEYS = [['dashboard-board'], ['dashboard-graph'], ['issue-detail'], ['issue-suggestion']];
const REFRESH_QUERY_KEYS = [['dashboard-board'], ['dashboard-graph'], ['projects'], ['admin-settings']];

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
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [confirmModalData, setConfirmModalData] = useState(null);
  const [confirmModalOpened, setConfirmModalOpened] = useState(false);

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

  const view = state.view === 'settings' && !user.is_admin ? 'board' : state.view;
  const pmProjects = new Set(projects.filter((p) => p.role === 'pm').map((p) => p.key));
  const canMoveStatus = (card) => user.is_admin || pmProjects.has(card.project_key);
  const selectIssue = (issue) => patch({ issue });
  const panelOpen = Boolean(state.issue) && view !== 'settings';

  return (
    <AppShell
      header={{ height: 60 }}
      aside={{ width: 440, breakpoint: 'sm', collapsed: { desktop: !panelOpen, mobile: !panelOpen } }}
      padding="md"
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
          view={view}
          onViewChange={(next) => patch({ view: next })}
        />
      </AppShell.Header>

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
            />
          </AppShell.Section>
        </AppShell.Aside>
      )}

      <AppShell.Main>
        {view === 'settings' && <Settings onBackToDashboard={() => patch({ view: 'board' })} />}
        {view === 'graph' && (
          <NetworkGraph selectedProject={state.project} onSelectIssue={selectIssue} selectedIssueKey={state.issue} />
        )}
        {(view === 'board' || view === 'list') && (
          <BoardView
            state={state}
            patch={patch}
            canMoveStatus={canMoveStatus}
            onMoveStatus={(card) => handleOpenConfirmAction(moveStatusProposal(card))}
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
