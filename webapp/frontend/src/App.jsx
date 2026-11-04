import React from 'react';
import {
  Container,
  Title,
  Text,
  Button,
  Badge,
  Group,
  Stack,
  Card,
  ThemeIcon,
} from '@mantine/core';
import { IconAlertTriangle, IconCheck, IconRocket } from '@tabler/icons-react';
import { notifications } from '@mantine/notifications';

export default function App() {
  const handleTestNotification = () => {
    notifications.show({
      title: 'Hệ thống sẵn sàng',
      message: 'Kết nối frontend Mantine và backend FastAPI thành công!',
      color: 'teal',
      icon: <IconCheck size={18} />,
    });
  };

  return (
    <Container size="md" py="xl">
      <Card shadow="sm" padding="lg" radius="md" withBorder>
        <Stack align="center" gap="md">
          <ThemeIcon size={48} radius="xl" color="blue" variant="light">
            <IconRocket size={28} />
          </ThemeIcon>
          <Badge size="lg" color="blue" variant="light">
            Early Risk Web MVP
          </Badge>
          <Title order={1} ta="center">
            Quản lý Tiến độ Dự án Jira
          </Title>
          <Text c="dimmed" size="lg" ta="center" maw={520}>
            Hệ thống phát hiện và cảnh báo sớm rủi ro trễ hạn bằng AI &amp; Temporal Graph Networks
          </Text>
          <Group mt="md">
            <Button
              leftSection={<IconAlertTriangle size={18} />}
              color="orange"
              onClick={handleTestNotification}
            >
              Kiểm tra thông báo
            </Button>
          </Group>
        </Stack>
      </Card>
    </Container>
  );
}
