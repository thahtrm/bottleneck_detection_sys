import React, { useState, useEffect } from 'react';
import {
  Card,
  Tabs,
  Group,
  Stack,
  Text,
  Badge,
  Select,
  Table,
  Button,
  Pagination,
  Skeleton,
  Center,
  Tooltip,
  ThemeIcon,
  Avatar,
  Box,
  Alert,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconLock,
  IconFlame,
  IconInbox,
  IconAlertCircle,
  IconRefresh,
  IconChevronRight,
  IconFilterOff,
} from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { getDashboardIssues, getDashboardStats } from '../api/client';

const PAGE_SIZE = 15;

/**
 * Tính toán thông tin hạn chót và số ngày còn lại / đã trễ
 */
function getDeadlineInfo(risk, duedate) {
  const dateStr = risk?.deadline_at || duedate;
  const label = risk?.deadline_label;

  if (!dateStr) {
    return {
      label: label || 'Chưa đặt',
      remainingText: null,
      color: 'gray',
    };
  }

  const targetDate = new Date(dateStr);
  if (isNaN(targetDate.getTime())) {
    return {
      label: label || dateStr,
      remainingText: null,
      color: 'gray',
    };
  }

  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const due = new Date(targetDate.getFullYear(), targetDate.getMonth(), targetDate.getDate());
  const diffDays = Math.round((due.getTime() - today.getTime()) / (1000 * 60 * 60 * 24));

  const formattedDate = targetDate.toLocaleDateString('vi-VN', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  });

  const displayLabel = label ? `${label} (${formattedDate})` : formattedDate;

  if (diffDays < 0) {
    const overdueDays = Math.abs(diffDays);
    return {
      label: displayLabel,
      remainingText: `Đã trễ ${overdueDays} ngày`,
      color: 'red',
    };
  }

  if (diffDays === 0) {
    return {
      label: displayLabel,
      remainingText: 'Hạn chót hôm nay',
      color: 'orange',
    };
  }

  if (diffDays === 1) {
    return {
      label: displayLabel,
      remainingText: 'Còn 1 ngày',
      color: 'orange',
    };
  }

  return {
    label: displayLabel,
    remainingText: `Còn ${diffDays} ngày`,
    color: diffDays <= 3 ? 'yellow' : 'gray',
  };
}

/**
 * Màu sắc đại diện cho loại issue Jira
 */
function getTypeColor(type) {
  const t = (type || '').toLowerCase();
  if (t.includes('bug')) return 'red';
  if (t.includes('story')) return 'green';
  if (t.includes('epic')) return 'violet';
  return 'blue';
}

/**
 * Badge mức ưu tiên Jira
 */
function getPriorityBadge(priority, priorityNorm) {
  const p = (priority || priorityNorm || '').toLowerCase();
  if (p.includes('highest') || p.includes('critical') || p.includes('urgent')) {
    return { label: priority || 'Khẩn', color: 'red' };
  }
  if (p.includes('high')) {
    return { label: priority || 'Cao', color: 'orange' };
  }
  if (p.includes('med')) {
    return { label: priority || 'TB', color: 'blue' };
  }
  if (p.includes('low')) {
    return { label: priority || 'Thấp', color: 'gray' };
  }
  return { label: priority || 'Bình thường', color: 'gray' };
}

/**
 * Tạo ký tự viết tắt đại diện cho tên người dùng
 */
function getInitials(name) {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
}

export default function TaskTable({
  selectedProject = '',
  searchQuery = '',
  activeCardFilter = '',
  onSelectIssue,
  selectedIssueKey = null,
}) {
  // Trạng thái cục bộ
  const [activeTab, setActiveTab] = useState('active_risk');
  const [levelFilter, setLevelFilter] = useState('ALL');
  const [sortBy, setSortBy] = useState('risk');
  const [page, setPage] = useState(1);

  // Lấy dữ liệu thống kê tổng quan để hiển thị số lượng trên từng Tab
  const { data: statsData } = useQuery({
    queryKey: ['dashboard-stats', selectedProject],
    queryFn: () => getDashboardStats(selectedProject || null),
    staleTime: 10000,
  });

  const stats = statsData || {};
  const atRiskCount = (stats.high_risk_count || 0) + (stats.med_risk_count || 0);

  // Tự động đồng bộ Tab khi click vào một trong các Stat Cards
  useEffect(() => {
    if (!activeCardFilter) return;

    if (
      activeCardFilter === 'at_risk' ||
      activeCardFilter === 'risk' ||
      activeCardFilter === 'increased_risk_24h' ||
      activeCardFilter === 'increased_risk'
    ) {
      setActiveTab('active_risk');
    } else if (activeCardFilter === 'blocked') {
      setActiveTab('blocked');
    } else if (activeCardFilter === 'critical') {
      setActiveTab('critical');
    } else if (
      activeCardFilter === 'resolved_recent' ||
      activeCardFilter === 'applied' ||
      activeCardFilter === 'done'
    ) {
      setActiveTab('done');
    }
    setPage(1);
  }, [activeCardFilter]);

  // Reset trang về 1 khi đổi bộ lọc dự án, tìm kiếm hoặc tab
  useEffect(() => {
    setPage(1);
  }, [selectedProject, searchQuery, activeTab, levelFilter, sortBy]);

  // Xây dựng params gửi lên API theo activeTab và filters
  const queryParams = {
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  };

  if (selectedProject) {
    queryParams.project = selectedProject;
  }

  if (searchQuery && searchQuery.trim()) {
    queryParams.q = searchQuery.trim();
  }

  // Mapping trạng thái theo Tab
  if (activeTab === 'active_risk') {
    queryParams.status_category = 'active';
  } else if (activeTab === 'active_all') {
    queryParams.status_category = 'active';
  } else if (activeTab === 'blocked') {
    queryParams.status_category = 'active';
    queryParams.blocked = true;
  } else if (activeTab === 'critical') {
    queryParams.status_category = 'active';
    queryParams.is_critical = true;
  } else if (activeTab === 'done') {
    queryParams.status_category = 'done';
  }

  // Bộ lọc mức độ rủi ro
  if (levelFilter && levelFilter !== 'ALL') {
    queryParams.level = levelFilter;
  }

  // Tiêu chí sắp xếp
  if (sortBy) {
    queryParams.sort_by = sortBy;
    queryParams.order = sortBy === 'deadline' ? 'asc' : 'desc';
  }

  // Fetch danh sách issues
  const {
    data: issuesData,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: [
      'dashboard-issues',
      selectedProject,
      searchQuery,
      activeTab,
      levelFilter,
      sortBy,
      page,
    ],
    queryFn: () => getDashboardIssues(queryParams),
    refetchInterval: 30000,
    staleTime: 10000,
  });

  const total = issuesData?.total || 0;
  const items = issuesData?.items || [];
  const totalPages = Math.ceil(total / PAGE_SIZE);

  // Định nghĩa danh sách các Tabs
  const tabItems = [
    {
      value: 'active_risk',
      label: 'Cần xử lý',
      count: atRiskCount,
      color: 'red',
    },
    {
      value: 'active_all',
      label: 'Tất cả mở',
      count: stats.total_open_issues || 0,
      color: 'gray',
    },
    {
      value: 'blocked',
      label: 'Bị chặn',
      count: stats.blocked_count || 0,
      color: 'pink',
    },
    {
      value: 'critical',
      label: 'Quan trọng',
      count: stats.critical_count || 0,
      color: 'grape',
    },
    {
      value: 'done',
      label: 'Đã xong',
      count: stats.resolved_recent_count || 0,
      color: 'teal',
    },
  ];

  return (
    <Card shadow="xs" padding="md" radius="md" withBorder>
      <Stack gap="md">
        {/* Header Tabs Mantine */}
        <Group justify="space-between" align="center" wrap="wrap">
          <Tabs
            value={activeTab}
            onChange={(val) => {
              if (val) {
                setActiveTab(val);
                setPage(1);
              }
            }}
          >
            <Tabs.List>
              {tabItems.map((tab) => (
                <Tabs.Tab
                  key={tab.value}
                  value={tab.value}
                  rightSection={
                    <Badge
                      size="xs"
                      variant={activeTab === tab.value ? 'filled' : 'light'}
                      color={tab.color}
                      circle
                    >
                      {tab.count}
                    </Badge>
                  }
                >
                  {tab.label}
                </Tabs.Tab>
              ))}
            </Tabs.List>
          </Tabs>

          <Button
            variant="subtle"
            size="xs"
            leftSection={<IconRefresh size={14} className={isFetching ? 'mantine-rotate' : ''} />}
            onClick={() => refetch()}
            loading={isFetching}
          >
            Làm mới
          </Button>
        </Group>

        {/* Hàng công cụ bộ lọc phụ */}
        <Group justify="space-between" align="center" wrap="wrap">
          <Group gap="sm" wrap="wrap">
            <Select
              size="xs"
              placeholder="Mức rủi ro"
              value={levelFilter}
              onChange={(val) => {
                setLevelFilter(val || 'ALL');
                setPage(1);
              }}
              data={[
                { value: 'ALL', label: 'Tất cả mức rủi ro' },
                { value: 'HIGH', label: 'Rủi ro Cao' },
                { value: 'MED', label: 'Rủi ro Trung bình' },
                { value: 'LOW', label: 'Rủi ro Thấp' },
              ]}
              w={170}
              clearable={false}
            />

            <Select
              size="xs"
              placeholder="Sắp xếp theo"
              value={sortBy}
              onChange={(val) => {
                setSortBy(val || 'risk');
                setPage(1);
              }}
              data={[
                { value: 'risk', label: 'Rủi ro (Cao nhất)' },
                { value: 'deadline', label: 'Hạn chót (Gần nhất)' },
                { value: 'updated', label: 'Mới cập nhật' },
              ]}
              w={180}
              clearable={false}
            />

            {(levelFilter !== 'ALL' || sortBy !== 'risk') && (
              <Button
                variant="subtle"
                color="gray"
                size="xs"
                leftSection={<IconFilterOff size={14} />}
                onClick={() => {
                  setLevelFilter('ALL');
                  setSortBy('risk');
                  setPage(1);
                }}
              >
                Đặt lại lọc
              </Button>
            )}
          </Group>

          <Text size="xs" c="dimmed">
            {total > 0 ? (
              <>
                Tổng số <strong>{total}</strong> công việc
              </>
            ) : null}
          </Text>
        </Group>

        {/* Báo lỗi nếu fetch thất bại */}
        {isError && (
          <Alert
            icon={<IconAlertCircle size={16} />}
            title="Lỗi tải danh sách công việc"
            color="red"
            variant="light"
          >
            <Group justify="space-between">
              <Text size="xs">{error?.message || 'Không thể kết nối đến máy chủ.'}</Text>
              <Button size="xs" color="red" variant="outline" onClick={() => refetch()}>
                Thử lại
              </Button>
            </Group>
          </Alert>
        )}

        {/* Bảng Mantine Table */}
        <Table.ScrollContainer minWidth={740}>
          <Table verticalSpacing="xs" highlightOnHover withRowBorders>
            <Table.Thead>
              <Table.Tr>
                <Table.Th style={{ width: '28%' }}>Key & Tóm tắt</Table.Th>
                <Table.Th style={{ width: '14%' }}>Loại & Ưu tiên</Table.Th>
                <Table.Th style={{ width: '12%' }}>Rủi ro</Table.Th>
                <Table.Th style={{ width: '10%' }}>Tín hiệu</Table.Th>
                <Table.Th style={{ width: '16%' }}>Hạn chót</Table.Th>
                <Table.Th style={{ width: '12%' }}>Phụ trách</Table.Th>
                <Table.Th style={{ width: '8%', textAlign: 'right' }}>Thao tác</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {isLoading ? (
                Array.from({ length: 6 }).map((_, idx) => (
                  <Table.Tr key={`skeleton-${idx}`}>
                    <Table.Td>
                      <Stack gap={4}>
                        <Skeleton height={14} width={70} radius="xs" />
                        <Skeleton height={12} width="90%" radius="xs" />
                      </Stack>
                    </Table.Td>
                    <Table.Td>
                      <Skeleton height={20} width={80} radius="sm" />
                    </Table.Td>
                    <Table.Td>
                      <Skeleton height={20} width={60} radius="sm" />
                    </Table.Td>
                    <Table.Td>
                      <Skeleton height={20} width={40} radius="sm" />
                    </Table.Td>
                    <Table.Td>
                      <Skeleton height={20} width={90} radius="sm" />
                    </Table.Td>
                    <Table.Td>
                      <Skeleton height={20} width={70} radius="sm" />
                    </Table.Td>
                    <Table.Td style={{ textAlign: 'right' }}>
                      <Skeleton height={24} width={50} radius="sm" ml="auto" />
                    </Table.Td>
                  </Table.Tr>
                ))
              ) : items.length === 0 ? (
                <Table.Tr>
                  <Table.Td colSpan={7}>
                    <Center py="xl">
                      <Stack align="center" gap="xs">
                        <ThemeIcon size={44} radius="xl" color="gray" variant="light">
                          <IconInbox size={24} />
                        </ThemeIcon>
                        <Text fw={600} size="sm">
                          Không tìm thấy công việc nào phù hợp
                        </Text>
                        <Text c="dimmed" size="xs" ta="center" maw={360}>
                          {searchQuery
                            ? `Không có kết quả nào cho từ khóa "${searchQuery}". Hãy thử tìm kiếm bằng từ khóa khác.`
                            : 'Không có công việc nào thỏa mãn bộ lọc hiện tại. Thử đổi tab hoặc bỏ bớt điều kiện lọc.'}
                        </Text>
                        {(levelFilter !== 'ALL' || sortBy !== 'risk') && (
                          <Button
                            variant="light"
                            size="xs"
                            onClick={() => {
                              setLevelFilter('ALL');
                              setSortBy('risk');
                              setPage(1);
                            }}
                          >
                            Xóa bộ lọc rủi ro
                          </Button>
                        )}
                      </Stack>
                    </Center>
                  </Table.Td>
                </Table.Tr>
              ) : (
                items.map((item) => {
                  const isSelected = item.key === selectedIssueKey;
                  const priority = getPriorityBadge(item.priority, item.priority_norm);
                  const typeColor = getTypeColor(item.issuetype);
                  const deadlineInfo = getDeadlineInfo(item.risk, item.duedate);
                  const riskLevel = item.risk?.level;

                  // Tín hiệu cảnh báo
                  const hasRisk = riskLevel === 'HIGH' || riskLevel === 'MED';
                  const isBlocked = Boolean(item.risk?.blocked);
                  const isCritical = Boolean(item.risk?.is_critical);
                  const hasSignals = hasRisk || isBlocked || isCritical;

                  return (
                    <Table.Tr
                      key={item.key}
                      onClick={() => onSelectIssue && onSelectIssue(item.key)}
                      style={{
                        cursor: 'pointer',
                        backgroundColor: isSelected
                          ? 'var(--mantine-color-blue-light)'
                          : undefined,
                        transition: 'background-color 150ms ease',
                      }}
                    >
                      {/* Cột 1: Key & Tóm tắt */}
                      <Table.Td>
                        <Stack gap={2}>
                          <Group gap={6} wrap="nowrap">
                            <Text
                              fw={700}
                              size="xs"
                              c="blue.7"
                              style={{ fontFamily: 'monospace' }}
                            >
                              {item.key}
                            </Text>
                            {item.story_points ? (
                              <Badge size="xs" variant="outline" color="gray">
                                {item.story_points} SP
                              </Badge>
                            ) : null}
                          </Group>
                          <Text size="xs" fw={500} lineClamp={2} title={item.summary}>
                            {item.summary}
                          </Text>
                        </Stack>
                      </Table.Td>

                      {/* Cột 2: Loại & Ưu tiên */}
                      <Table.Td>
                        <Stack gap={4} align="flex-start">
                          {item.issuetype ? (
                            <Badge size="xs" variant="light" color={typeColor}>
                              {item.issuetype}
                            </Badge>
                          ) : null}
                          {item.priority || item.priority_norm ? (
                            <Badge size="xs" variant="dot" color={priority.color}>
                              {priority.label}
                            </Badge>
                          ) : (
                            <Text size="xs" c="dimmed">
                              —
                            </Text>
                          )}
                        </Stack>
                      </Table.Td>

                      {/* Cột 3: Mức Rủi ro */}
                      <Table.Td>
                        <Stack gap={2} align="flex-start">
                          {riskLevel === 'HIGH' ? (
                            <Badge color="red" variant="filled" size="sm">
                              Cao
                            </Badge>
                          ) : riskLevel === 'MED' ? (
                            <Badge color="orange" variant="filled" size="sm">
                              TB
                            </Badge>
                          ) : riskLevel === 'LOW' ? (
                            <Badge color="teal" variant="light" size="sm">
                              Thấp
                            </Badge>
                          ) : (
                            <Badge color="gray" variant="subtle" size="sm">
                              —
                            </Badge>
                          )}

                          {item.risk?.delay_value !== undefined &&
                          item.risk?.delay_value !== null ? (
                            <Text size="xs" c="dimmed" style={{ fontSize: '0.7rem' }}>
                              P(trễ): {(item.risk.delay_value * 100).toFixed(0)}%
                            </Text>
                          ) : null}
                        </Stack>
                      </Table.Td>

                      {/* Cột 4: Tín hiệu */}
                      <Table.Td>
                        <Group gap={4} wrap="nowrap">
                          {hasRisk && (
                            <Tooltip label="Nguy cơ trễ hạn tiến độ" withArrow>
                              <ThemeIcon color="red" variant="light" size="sm" radius="xl">
                                <IconAlertTriangle size={13} />
                              </ThemeIcon>
                            </Tooltip>
                          )}

                          {isBlocked && (
                            <Tooltip label="Đang bị chặn (Blocker)" withArrow>
                              <ThemeIcon color="pink" variant="light" size="sm" radius="xl">
                                <IconLock size={13} />
                              </ThemeIcon>
                            </Tooltip>
                          )}

                          {isCritical && (
                            <Tooltip label="Nhiệm vụ trọng yếu (Top 5%)" withArrow>
                              <ThemeIcon color="grape" variant="light" size="sm" radius="xl">
                                <IconFlame size={13} />
                              </ThemeIcon>
                            </Tooltip>
                          )}

                          {!hasSignals && (
                            <Text size="xs" c="dimmed">
                              —
                            </Text>
                          )}
                        </Group>
                      </Table.Td>

                      {/* Cột 5: Hạn chót */}
                      <Table.Td>
                        <Stack gap={2} align="flex-start">
                          <Text size="xs" fw={500} lineClamp={1} title={deadlineInfo.label}>
                            {deadlineInfo.label}
                          </Text>
                          {deadlineInfo.remainingText ? (
                            <Badge
                              size="xs"
                              variant="light"
                              color={deadlineInfo.color}
                              radius="sm"
                            >
                              {deadlineInfo.remainingText}
                            </Badge>
                          ) : null}
                        </Stack>
                      </Table.Td>

                      {/* Cột 6: Người phụ trách */}
                      <Table.Td>
                        <Group gap={6} wrap="nowrap">
                          <Avatar size={22} radius="xl" color="blue" variant="light">
                            {getInitials(item.assignee_name)}
                          </Avatar>
                          <Text size="xs" lineClamp={1} title={item.assignee_name || 'Chưa giao'}>
                            {item.assignee_name || (
                              <Text component="span" c="dimmed" size="xs">
                                Chưa giao
                              </Text>
                            )}
                          </Text>
                        </Group>
                      </Table.Td>

                      {/* Cột 7: Thao tác */}
                      <Table.Td style={{ textAlign: 'right' }}>
                        <Button
                          size="xs"
                          variant={isSelected ? 'filled' : 'light'}
                          color="blue"
                          rightSection={<IconChevronRight size={12} />}
                          onClick={(e) => {
                            e.stopPropagation();
                            onSelectIssue && onSelectIssue(item.key);
                          }}
                        >
                          Chi tiết
                        </Button>
                      </Table.Td>
                    </Table.Tr>
                  );
                })
              )}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>

        {/* Phân trang Pagination */}
        {total > PAGE_SIZE && (
          <Group justify="space-between" align="center" pt="xs" wrap="wrap">
            <Text size="xs" c="dimmed">
              Hiển thị <strong>{(page - 1) * PAGE_SIZE + 1}</strong> -{' '}
              <strong>{Math.min(page * PAGE_SIZE, total)}</strong> trên tổng số{' '}
              <strong>{total}</strong> công việc
            </Text>
            <Pagination
              value={page}
              onChange={setPage}
              total={totalPages}
              size="sm"
              withEdges
            />
          </Group>
        )}
      </Stack>
    </Card>
  );
}
