import React, { useState } from 'react';
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
} from '@mantine/core';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { AuthProvider, useAuth } from './context/AuthContext';
import { getProjects } from './api/client';
import Login from './pages/Login';
import Header from './components/Header';
import StatCards from './components/StatCards';

function AppContent() {
  const { user, loading } = useAuth();
  const queryClient = useQueryClient();

  const [selectedProject, setSelectedProject] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState('');
  const [isRefreshing, setIsRefreshing] = useState(false);

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
        />
      </AppShell.Header>

      <AppShell.Main>
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

            {/* Khối thông tin dự án hiện tại */}
            <Card shadow="xs" padding="lg" radius="md" withBorder>
              <Stack gap="xs">
                <Title order={3}>
                  {selectedProject
                    ? `Dự án: ${
                        projects.find(
                          (p) => (p.key || p.id) === selectedProject
                        )?.name || selectedProject
                      }`
                    : 'Tổng quan tất cả dự án'}
                </Title>
                <Text c="dimmed" size="sm">
                  Hệ thống phát hiện sớm rủi ro tiến độ công việc từ Jira.
                  Danh sách công việc và đề xuất hỗ trợ từ mô hình AI sẽ được hiển thị tại đây.
                </Text>
              </Stack>
            </Card>
          </Stack>
        </Container>
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
