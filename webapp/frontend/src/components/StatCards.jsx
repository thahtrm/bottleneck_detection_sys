import React from 'react';
import {
  SimpleGrid,
  Paper,
  Text,
  Group,
  ThemeIcon,
  Skeleton,
  Box,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconTrendingUp,
  IconBarrierBlock,
  IconFlame,
  IconCircleCheck,
} from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { getDashboardStats } from '../api/client';

export default function StatCards({
  selectedProject = '',
  onFilterByCard,
  activeFilter = '',
}) {
  const { data, isLoading } = useQuery({
    queryKey: ['dashboard-stats', selectedProject],
    queryFn: () => getDashboardStats(selectedProject || null),
    refetchInterval: 30000,
    staleTime: 10000,
  });

  if (isLoading) {
    return (
      <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 5 }} spacing="md">
        {Array.from({ length: 5 }).map((_, idx) => (
          <Skeleton key={idx} height={105} radius="md" />
        ))}
      </SimpleGrid>
    );
  }

  const stats = data || {};
  const atRiskCount = (stats.high_risk_count || 0) + (stats.med_risk_count || 0);

  const cards = [
    {
      id: 'at_risk',
      filterType: 'at_risk',
      title: 'Nguy cơ trễ',
      value: atRiskCount,
      subtitle: `${stats.high_risk_count || 0} Cao • ${stats.med_risk_count || 0} TB`,
      icon: IconAlertTriangle,
      color: 'red',
    },
    {
      id: 'increased_risk_24h',
      filterType: 'increased_risk_24h',
      title: 'Tăng rủi ro (24h)',
      value: stats.increased_risk_24h_count || 0,
      subtitle: 'So với hôm qua',
      icon: IconTrendingUp,
      color: 'orange',
    },
    {
      id: 'blocked',
      filterType: 'blocked',
      title: 'Đang bị chặn',
      value: stats.blocked_count || 0,
      subtitle: 'Cần gỡ vướng',
      icon: IconBarrierBlock,
      color: 'pink',
    },
    {
      id: 'critical',
      filterType: 'critical',
      title: 'Task quan trọng',
      value: stats.critical_count || 0,
      subtitle: 'Top 5% mô hình',
      icon: IconFlame,
      color: 'grape',
    },
    {
      id: 'resolved_recent',
      filterType: 'resolved_recent',
      title: 'Đã xử lý (7 ngày)',
      value: stats.applied_actions_count || 0,
      subtitle: `${stats.resolved_recent_count || 0} đã xong`,
      icon: IconCircleCheck,
      color: 'teal',
    },
  ];

  return (
    <SimpleGrid cols={{ base: 1, sm: 2, md: 3, lg: 5 }} spacing="md">
      {cards.map((card) => {
        const IconComponent = card.icon;
        const isActive = activeFilter === card.filterType;

        return (
          <Paper
            key={card.id}
            withBorder
            p="md"
            radius="md"
            shadow={isActive ? 'sm' : 'xs'}
            onClick={() => onFilterByCard && onFilterByCard(card.filterType)}
            style={{
              cursor: onFilterByCard ? 'pointer' : 'default',
              transition: 'transform 150ms ease, box-shadow 150ms ease, border-color 150ms ease',
              borderWidth: isActive ? 2 : 1,
              borderColor: isActive ? `var(--mantine-color-${card.color}-filled)` : undefined,
              userSelect: 'none',
            }}
            styles={{
              root: {
                '&:hover': {
                  transform: onFilterByCard ? 'translateY(-2px)' : 'none',
                  boxShadow: 'var(--mantine-shadow-sm)',
                },
              },
            }}
            role="button"
            tabIndex={0}
            aria-label={`${card.title}: ${card.value}, ${card.subtitle}`}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                onFilterByCard && onFilterByCard(card.filterType);
              }
            }}
          >
            <Group justify="space-between" align="flex-start" wrap="nowrap">
              <Box>
                <Text size="xs" c="dimmed" fw={700} tt="uppercase" style={{ letterSpacing: '0.5px' }}>
                  {card.title}
                </Text>
                <Text fw={700} size="xl" mt={4} style={{ fontSize: '1.75rem', lineHeight: 1.2 }}>
                  {card.value}
                </Text>
              </Box>

              <ThemeIcon
                color={card.color}
                variant="light"
                size="xl"
                radius="md"
              >
                <IconComponent size={24} stroke={1.5} />
              </ThemeIcon>
            </Group>

            <Text size="xs" c="dimmed" mt={8}>
              {card.subtitle}
            </Text>
          </Paper>
        );
      })}
    </SimpleGrid>
  );
}
