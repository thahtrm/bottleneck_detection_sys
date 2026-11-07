import React, { useState, useEffect } from 'react';
import {
  AppShell,
  Center,
  Loader,
  Text,
  Container,
  Card,
  Stack,
  Title,
  Group,
  Button,
  Grid,
  SegmentedControl,
} from '@mantine/core';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './context/AuthContext';
import { getProjects } from './api/client';
import Login from './pages/Login';
import Settings from './pages/Settings';
import Header from './components/Header';
import StatCards from './components/StatCards';
import TaskTable from './components/TaskTable';
import IssuePanel from './components/IssuePanel';
import ActionConfirmModal from './components/ActionConfirmModal';
import NetworkGraph from './components/NetworkGraph';

function AppContent() {
  const { user, loading } = useAuth();
  const queryClient = useQueryClient();

  const [currentView, setCurrentView] = useState('dashboard');
  const [selectedProject, setSelectedProject] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [selectedIssueKey, setSelectedIssueKey] = useState(null);
  const [confirmModalData, setConfirmModalData] = useState(null);
  const [confirmModalOpened, setConfirmModalOpened] = useState(false);

  // Nếu người dùng không phải admin thì tự động quay về dashboard
  useEffect(() => {
    if (user && !user.is_admin && currentView === 'settings') {
      setCurrentView('dashboard');
    }
  }, [user, currentView]);

  // Callback mở modal xác nhận hành động PM
  const handleOpenConfirmAction = (proposalData) => {
    setConfirmModalData(proposalData);
    setConfirmModalOpened(true);
  };

  // Callback làm mới dữ liệu sau khi xác nhận & ghi Jira thành công
  const handleActionSuccess = async () => {
    const key = confirmModalData?.issueKey || selectedIssueKey;
    await Promise.all([
      key ? queryClient.invalidateQueries({ queryKey: ['issue-detail', key] }) : Promise.resolve(),
      key ? queryClient.invalidateQueries({ queryKey: ['issue-suggestion', key] }) : Promise.resolve(),
      queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] }),
      queryClient.invalidateQueries({ queryKey: ['dashboard-issues'] }),
      queryClient.invalidateQueries({ queryKey: ['dashboard-graph'] }),
    ]);
  };

  // Reset selected issue khi đổi dự án
  useEffect(() => {
    setSelectedIssueKey(null);
  }, [selectedProject]);

  // Lấy danh sách dự án từ API
  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: getProjects,
    enabled: Boolean(user),
    staleTime: 30000,
  });

  // Xử lý làm mới dữ liệu
  const handleRefresh = async () => {
    setIsRefreshing(true);
    try {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['dashboard-stats'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-issues'] }),
        queryClient.invalidateQueries({ queryKey: ['dashboard-graph'] }),
        queryClient.invalidateQueries({ queryKey: ['projects'] }),
        queryClient.invalidateQueries({ queryKey: ['admin-settings'] }),
      ]);
    } finally {
      setIsRefreshing(false);
    }
  };

  // Lọc nhanh khi click vào một trong 5 Stat Cards (toggle nếu click lại)
  const handleFilterByCard = (filterType) => {
    setActiveFilter((prev) => (prev === filterType ? '' : filterType));
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

  return (
    <AppShell header={{ height: 60 }} padding="md">
      <AppShell.Header>
        <Header
          projects={projects}
          selectedProject={selectedProject}
          onSelectProject={setSelectedProject}
          searchQuery={searchQuery}
          onSearchChange={setSearchQuery}
          onRefresh={handleRefresh}
          isRefreshing={isRefreshing}
          currentView={currentView}
          onViewChange={setCurrentView}
        />
      </AppShell.Header>

      <AppShell.Main>
        {currentView === 'settings' ? (
          <Container size="xl" py="md">
            <Settings onBackToDashboard={() => setCurrentView('dashboard')} />
          </Container>
        ) : (
          <Container size="xl" py="md">
            <Stack gap="lg">
              {/* Bộ thẻ thống kê rủi ro thời gian thực */}
              <StatCards
                selectedProject={selectedProject}
                onFilterByCard={handleFilterByCard}
                activeFilter={activeFilter}
              />

              {/* Thông báo bộ lọc thẻ đang kích hoạt */}
              {activeFilter && (
                <Card
                  withBorder
                  padding="sm"
                  radius="md"
                  bg="var(--mantine-color-blue-light)"
                >
                  <Group justify="space-between" align="center">
                    <Text size="sm" fw={500}>
                      Đang lọc theo tiêu chí: <strong>{activeFilter}</strong>
                    </Text>
                    <Button
                      variant="subtle"
                      size="xs"
                      color="blue"
                      onClick={() => setActiveFilter('')}
                    >
                      Bỏ lọc
                    </Button>
                  </Group>
                </Card>
              )}

              {/* Thanh chuyển đổi chế độ xem nhanh: Bảng Task vs Đồ thị Mạng lưới */}
              <Group justify="space-between" align="center">
                <SegmentedControl
                  size="sm"
                  value={currentView === 'graph' ? 'graph' : 'table'}
                  onChange={(val) => setCurrentView(val === 'graph' ? 'graph' : 'dashboard')}
                  data={[
                    { label: '📋 Danh sách Task & Rủi ro', value: 'table' },
                    { label: '🕸️ Đồ thị Mạng lưới & Điểm nghẽn', value: 'graph' },
                  ]}
                />
              </Group>

              {/* Bố cục lưới 2 cột: (Trái: Bảng Task hoặc Đồ thị) và (Phải: Panel Chi tiết) */}
              <Grid gutter="md" align="stretch">
                <Grid.Col span={{ base: 12, lg: 7 }}>
                  {currentView === 'graph' ? (
                    <NetworkGraph
                      selectedProject={selectedProject}
                      onSelectIssue={setSelectedIssueKey}
                      selectedIssueKey={selectedIssueKey}
                    />
                  ) : (
                    <TaskTable
                      selectedProject={selectedProject}
                      searchQuery={searchQuery}
                      activeCardFilter={activeFilter}
                      onSelectIssue={setSelectedIssueKey}
                      selectedIssueKey={selectedIssueKey}
                    />
                  )}
                </Grid.Col>

                <Grid.Col span={{ base: 12, lg: 5 }}>
                  <IssuePanel
                    key={selectedIssueKey || 'placeholder'}
                    issueKey={selectedIssueKey}
                    onClose={() => setSelectedIssueKey(null)}
                    onOpenConfirmAction={handleOpenConfirmAction}
                    projects={projects}
                    onSelectIssue={setSelectedIssueKey}
                  />
                </Grid.Col>
              </Grid>
            </Stack>
          </Container>
        )}

        {/* Modal Xác nhận & Ghi Jira */}
        <ActionConfirmModal
          opened={confirmModalOpened}
          onClose={() => setConfirmModalOpened(false)}
          proposalData={confirmModalData}
          onSuccess={handleActionSuccess}
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
