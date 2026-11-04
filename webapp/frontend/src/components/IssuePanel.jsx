import React from 'react';
import {
  Card,
  Stack,
  Group,
  Title,
  Text,
  Badge,
  Button,
  ActionIcon,
  Center,
  ThemeIcon,
  Skeleton,
  Paper,
} from '@mantine/core';
import {
  IconX,
  IconSparkles,
  IconCpu,
  IconClock,
  IconAlertTriangle,
} from '@tabler/icons-react';

export default function IssuePanel({ issueKey, onClose }) {
  if (!issueKey) {
    return (
      <Card shadow="xs" padding="xl" radius="md" withBorder h="100%">
        <Center h="100%" py={60}>
          <Stack align="center" gap="sm" maw={320} ta="center">
            <ThemeIcon size={56} radius="xl" color="blue" variant="light">
              <IconSparkles size={28} />
            </ThemeIcon>
            <Title order={4} fw={600}>
              Chi tiết công việc & Đề xuất AI
            </Title>
            <Text c="dimmed" size="xs">
              Nhấp vào bất kỳ công việc nào trong bảng bên trái để xem phân tích rủi ro,
              yếu tố cảnh báo và khuyến nghị hành động từ mô hình AI.
            </Text>
          </Stack>
        </Center>
      </Card>
    );
  }

  return (
    <Card shadow="xs" padding="md" radius="md" withBorder>
      <Stack gap="md">
        {/* Header Panel */}
        <Group justify="space-between" align="center">
          <Group gap="xs">
            <Badge size="lg" color="blue" variant="filled">
              {issueKey}
            </Badge>
            <Text fw={600} size="sm">
              Chi tiết rủi ro & Đề xuất LLM
            </Text>
          </Group>

          {onClose && (
            <ActionIcon
              variant="subtle"
              color="gray"
              size="sm"
              onClick={onClose}
              aria-label="Đóng panel chi tiết"
            >
              <IconX size={16} />
            </ActionIcon>
          )}
        </Group>

        {/* Thông báo chuẩn bị cho Task 5 */}
        <Paper p="sm" radius="md" bg="var(--mantine-color-blue-light)" withBorder>
          <Group gap="xs" wrap="nowrap" align="flex-start">
            <ThemeIcon size="sm" color="blue" variant="light">
              <IconCpu size={14} />
            </ThemeIcon>
            <Stack gap={2}>
              <Text size="xs" fw={600}>
                Panel Chi tiết Task & Gợi ý LLM (Task 5)
              </Text>
              <Text size="xs" c="dimmed">
                Tính năng phân tích xác suất trễ hạn (p_delay), điểm quan trọng (criticality),
                yếu tố rủi ro và hành động đề xuất từ Ollama qwen3:1.7b đang được kết nối.
              </Text>
            </Stack>
          </Group>
        </Paper>

        {/* Skeletons mô phỏng nội dung sắp tới */}
        <Stack gap="xs">
          <Text size="xs" fw={600} c="dimmed">
            CHỈ SỐ RỦI RO DỰ BÁO
          </Text>
          <Group grow>
            <Skeleton height={60} radius="sm" />
            <Skeleton height={60} radius="sm" />
          </Group>

          <Text size="xs" fw={600} c="dimmed" mt="xs">
            YẾU TỐ CẢNH BÁO CHÍNH
          </Text>
          <Skeleton height={28} radius="xs" />
          <Skeleton height={28} radius="xs" />
          <Skeleton height={28} radius="xs" />

          <Text size="xs" fw={600} c="dimmed" mt="xs">
            HÀNH ĐỘNG KHUYẾN NGHỊ (AI)
          </Text>
          <Skeleton height={80} radius="sm" />
        </Stack>
      </Stack>
    </Card>
  );
}
