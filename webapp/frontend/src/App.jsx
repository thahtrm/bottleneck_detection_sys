import React from 'react';
import {
  AppShell,
  Center,
  Loader,
  Text,
  Group,
  ThemeIcon,
  Title,
  Badge,
  Button,
  Container,
  Card,
  Stack,
} from '@mantine/core';
import { IconLogout, IconRocket, IconUser } from '@tabler/icons-react';
import { AuthProvider, useAuth } from './context/AuthContext';
import Login from './pages/Login';

function AppContent() {
  const { user, loading, logout } = useAuth();

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
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <ThemeIcon size="lg" radius="md" color="blue" variant="filled">
              <IconRocket size={20} />
            </ThemeIcon>
            <div>
              <Title order={4}>Early Risk Web</Title>
            </div>
          </Group>

          <Group gap="md">
            <Badge
              color={user.is_admin ? 'red' : 'blue'}
              variant="light"
              size="lg"
            >
              {user.is_admin ? 'Admin' : 'PM / Viewer'}
            </Badge>
            <Group gap="xs">
              <IconUser size={18} />
              <Text fw={500} size="sm">
                {user.name || user.email}
              </Text>
            </Group>
            <Button
              variant="light"
              color="gray"
              size="xs"
              leftSection={<IconLogout size={16} />}
              onClick={logout}
            >
              Đăng xuất
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Main>
        <Container size="lg" py="xl">
          <Card shadow="sm" padding="xl" radius="md" withBorder>
            <Stack gap="sm">
              <Title order={2}>Xin chào, {user.name}!</Title>
              <Text c="dimmed" size="md">
                Chào mừng bạn quay trở lại với hệ thống phát hiện và cảnh báo sớm rủi ro tiến độ dự án Jira.
              </Text>
            </Stack>
          </Card>
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
