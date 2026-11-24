import React, { useMemo, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Drawer,
  Group,
  Loader,
  Menu,
  ScrollArea,
  SegmentedControl,
  Stack,
  Table,
  Text,
  UnstyledButton,
} from '@mantine/core';
import { useMediaQuery } from '@mantine/hooks';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  IconDownload,
  IconRefresh,
  IconX,
} from '@tabler/icons-react';
import { downloadOverviewExport, getProjectOverview } from '../../api/client';
import '../../styles/kaggleTokens.css';
import classes from './overview.module.css';

const ACTOR_TABS = [
  { value: 'all', label: 'Tất cả' },
  { value: 'person', label: 'Người' },
  { value: 'blocker', label: 'Issue chặn' },
  { value: 'status', label: 'Giai đoạn' },
];

const CHART_TABS = [
  { value: 'shap', label: 'SHAP' },
  { value: 'risk', label: 'Phân bố' },
  { value: 'deps', label: 'Phụ thuộc' },
];

const KIND_LABEL = {
  person: 'Người',
  blocker: 'Issue chặn',
  status: 'Giai đoạn',
};

function levelColor(level) {
  if (level === 'HIGH') return 'red';
  if (level === 'MED') return 'orange';
  if (level === 'LOW') return 'gray';
  return 'gray';
}

function formatPDelay(value) {
  if (value == null || Number.isNaN(Number(value))) return '—';
  return Number(value).toFixed(2);
}

function KpiCell({ label, value, hint, active, onClick }) {
  return (
    <UnstyledButton
      className={classes.kpiCell}
      data-active={active ? 'true' : undefined}
      onClick={onClick}
      type="button"
    >
      <Text className={classes.kpiLabel}>{label}</Text>
      <Text className={classes.kpiValue}>{value}</Text>
      {hint ? (
        <Text className={classes.kpiHint} c="dimmed">
          {hint}
        </Text>
      ) : null}
    </UnstyledButton>
  );
}

function ExplainDrawer({ opened, onClose, explain, onOpenBoard }) {
  if (!explain) return null;
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      position="right"
      size={440}
      padding="md"
      title={
        <Stack gap={4}>
          <Group gap="xs" wrap="nowrap">
            <Text fw={700}>{explain.key}</Text>
            {explain.level ? (
              <Badge color={levelColor(explain.level)} variant="filled" size="sm">
                {explain.level}
              </Badge>
            ) : null}
          </Group>
          <Text size="sm" c="dimmed" lineClamp={2}>
            {explain.summary}
          </Text>
        </Stack>
      }
      closeButtonProps={{ 'aria-label': 'Đóng' }}
      classNames={{ content: classes.drawerContent }}
    >
      <Stack gap="md">
        <Group gap="md">
          <Text size="sm">
            p_delay: <strong>{formatPDelay(explain.p_delay)}</strong>
          </Text>
          <Button size="compact-sm" variant="light" onClick={() => onOpenBoard(explain.key)}>
            Mở trên Bảng
          </Button>
        </Group>

        <div>
          <Text className={classes.sectionOverline}>Tác nhân cấu trúc</Text>
          <Stack gap="xs" mt="xs">
            {(explain.structural_factors || []).map((factor) => (
              <Box key={factor.kind} className={classes.factorRow}>
                <Text size="sm" fw={600}>
                  {factor.label}
                </Text>
                <Text size="sm" c="dimmed">
                  {factor.evidence}
                </Text>
              </Box>
            ))}
          </Stack>
        </div>

        <div>
          <Text className={classes.sectionOverline}>SHAP</Text>
          <Alert mt="xs" color="gray" variant="light">
            {explain.shap_status || 'Chưa có SHAP cho snapshot này'}
          </Alert>
        </div>

        <div>
          <Text className={classes.sectionOverline}>Downstream (blocks)</Text>
          {(explain.downstream || []).length === 0 ? (
            <Text size="sm" c="dimmed" mt="xs">
              (không có)
            </Text>
          ) : (
            <Stack gap={4} mt="xs">
              {explain.downstream.map((key) => (
                <Text key={key} size="sm">
                  {key}
                </Text>
              ))}
            </Stack>
          )}
        </div>
      </Stack>
    </Drawer>
  );
}

export default function OverviewPage({
  project,
  selectedIssueKey,
  onSelectIssue,
  onOpenBoard,
}) {
  const queryClient = useQueryClient();
  const isMobile = useMediaQuery('(max-width: 61.99em)');
  const [actorTab, setActorTab] = useState('all');
  const [chartTab, setChartTab] = useState('risk');
  const [tableFilter, setTableFilter] = useState(null);
  const [exporting, setExporting] = useState(false);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ['project-overview', project],
    queryFn: () => getProjectOverview(project),
    enabled: Boolean(project),
    staleTime: 15000,
  });

  const actors = useMemo(() => {
    if (!data) return [];
    if (actorTab === 'all') return data.actors || [];
    return data.actors_by_kind?.[actorTab] || [];
  }, [data, actorTab]);

  const filteredIssues = useMemo(() => {
    if (!data?.issues) return [];
    let rows = data.issues;
    if (!tableFilter) return rows;
    if (tableFilter.type === 'level' && tableFilter.value === 'HIGH_MED') {
      rows = rows.filter((r) => r.level === 'HIGH' || r.level === 'MED');
    } else if (tableFilter.type === 'blocked') {
      rows = rows.filter((r) => r.blocked || (r.blocked_by || []).length > 0);
    } else if (tableFilter.type === 'overdue') {
      rows = rows.filter((r) => r.overdue);
    } else if (tableFilter.type === 'assignee') {
      rows = rows.filter((r) => r.assignee === tableFilter.value);
    } else if (tableFilter.type === 'status') {
      rows = rows.filter((r) => r.status === tableFilter.value);
    } else if (tableFilter.type === 'open') {
      rows = rows;
    }
    return rows;
  }, [data, tableFilter]);

  const explain = selectedIssueKey && data?.explain?.[selectedIssueKey]
    ? data.explain[selectedIssueKey]
    : selectedIssueKey
      ? {
          key: selectedIssueKey,
          summary: '',
          level: null,
          p_delay: null,
          structural_factors: [],
          downstream: [],
          shap: null,
          shap_status: 'Issue không có trong snapshot open hiện tại',
        }
      : null;

  const handleExport = async (format) => {
    if (!project) return;
    setExporting(true);
    try {
      const { blob, filename } = await downloadOverviewExport(project, format);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      // eslint-disable-next-line no-alert
      window.alert(err?.message || 'Xuất báo cáo thất bại');
    } finally {
      setExporting(false);
    }
  };

  const handleActorClick = (actor) => {
    if (actor.kind === 'person') {
      setTableFilter({ type: 'assignee', value: actor.name });
    } else if (actor.kind === 'blocker') {
      onSelectIssue(actor.id);
    } else if (actor.kind === 'status') {
      setTableFilter({ type: 'status', value: actor.name });
    }
  };

  if (!project) {
    return (
      <Box className={`erw-overview-scope ${classes.root}`} p="md">
        <Text c="dimmed">Chọn dự án trên thanh trên để xem tổng quan.</Text>
      </Box>
    );
  }

  if (isLoading) {
    return (
      <Box className={`erw-overview-scope ${classes.root}`} p="xl">
        <Group gap="sm">
          <Loader size="sm" type="dots" />
          <Text size="sm" c="dimmed">
            Đang tải tổng quan...
          </Text>
        </Group>
      </Box>
    );
  }

  if (error) {
    return (
      <Box className={`erw-overview-scope ${classes.root}`} p="md">
        <Alert color="red" title="Không tải được tổng quan">
          {error.message || 'Lỗi không xác định'}
        </Alert>
      </Box>
    );
  }

  const kpi = data.kpi || {};
  const sprint = data.sprint;
  const maxRisk = Math.max(1, ...(data.risk_distribution || []).map((d) => d.count));

  return (
    <Box className={`erw-overview-scope ${classes.root}`}>
      <Stack gap="md" className={classes.inner}>
        {/* [A] Header strip */}
        <Group justify="space-between" align="flex-start" wrap="wrap" gap="sm">
          <Stack gap={4}>
            <Text className={classes.pageTitle}>
              {data.project} · {data.name}
            </Text>
            <Text size="sm" c="dimmed">
              {sprint
                ? `${sprint.name} · ${sprint.done}/${sprint.committed} (${sprint.done_pct}% done${
                    sprint.expected_pct != null ? ` · kỳ vọng ${sprint.expected_pct}%` : ''
                  })`
                : data.sprint_line || 'Không có sprint active'}
              {' · '}
              {data.as_of_label}
            </Text>
          </Stack>
          <Group gap="xs">
            <Button
              variant="default"
              size="sm"
              radius="xl"
              leftSection={<IconRefresh size={16} />}
              loading={isFetching}
              onClick={() => {
                queryClient.invalidateQueries({ queryKey: ['project-overview', project] });
                refetch();
              }}
            >
              Làm mới
            </Button>
            <Menu shadow="md" width={180} position="bottom-end">
              <Menu.Target>
                <Button
                  variant="filled"
                  color="dark"
                  size="sm"
                  radius="xl"
                  leftSection={<IconDownload size={16} />}
                  loading={exporting}
                >
                  Xuất PDF/MD
                </Button>
              </Menu.Target>
              <Menu.Dropdown>
                <Menu.Item onClick={() => handleExport('md')}>Xuất Markdown</Menu.Item>
                <Menu.Item onClick={() => handleExport('pdf')}>Xuất PDF</Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Group>
        </Group>

        {/* [B] KPI strip */}
        <div className={classes.kpiStrip}>
          <KpiCell
            label="Open"
            value={kpi.open ?? '—'}
            hint={kpi.open_delta_24h ? `+${kpi.open_delta_24h} 24h` : undefined}
            active={tableFilter?.type === 'open'}
            onClick={() => setTableFilter({ type: 'open' })}
          />
          <KpiCell
            label="Done (sprint)"
            value={
              kpi.sprint_committed != null
                ? `${kpi.sprint_done}/${kpi.sprint_committed}`
                : '—'
            }
          />
          <KpiCell
            label="HIGH / MED"
            value={`${kpi.high ?? 0} / ${kpi.med ?? 0}`}
            hint={kpi.high_delta_24h ? `↑ HIGH ${kpi.high_delta_24h}` : undefined}
            active={tableFilter?.type === 'level'}
            onClick={() => setTableFilter({ type: 'level', value: 'HIGH_MED' })}
          />
          <KpiCell
            label="Blocked"
            value={kpi.blocked ?? '—'}
            active={tableFilter?.type === 'blocked'}
            onClick={() => setTableFilter({ type: 'blocked' })}
          />
          <KpiCell
            label="Forecast delay"
            value={formatPDelay(kpi.forecast_delay)}
            hint={kpi.overdue ? `${kpi.overdue} trễ hạn` : undefined}
            active={tableFilter?.type === 'overdue'}
            onClick={() => setTableFilter({ type: 'overdue' })}
          />
        </div>

        {tableFilter ? (
          <Group gap="xs">
            <Badge variant="outline" color="gray">
              Lọc bảng:{' '}
              {tableFilter.type === 'assignee'
                ? `assignee=${tableFilter.value}`
                : tableFilter.type === 'status'
                  ? `status=${tableFilter.value}`
                  : tableFilter.type}
            </Badge>
            <ActionIcon
              variant="subtle"
              size="sm"
              aria-label="Xóa lọc"
              onClick={() => setTableFilter(null)}
            >
              <IconX size={14} />
            </ActionIcon>
          </Group>
        ) : null}

        {/* [C] Main split */}
        <div className={classes.split}>
          <Box className={classes.panel}>
            <Group justify="space-between" mb="sm" wrap="wrap" gap="xs">
              <Text className={classes.panelTitle}>Tác nhân ảnh hưởng</Text>
              <SegmentedControl
                size="xs"
                value={actorTab}
                onChange={setActorTab}
                data={ACTOR_TABS}
              />
            </Group>
            <ScrollArea.Autosize mah={isMobile ? 280 : 360}>
              <Table highlightOnHover horizontalSpacing="sm" verticalSpacing={6}>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>#</Table.Th>
                    <Table.Th>Tác nhân</Table.Th>
                    <Table.Th>Loại</Table.Th>
                    <Table.Th>Ảnh hưởng</Table.Th>
                    <Table.Th>Impact</Table.Th>
                    <Table.Th>Gợi ý</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {actors.length === 0 ? (
                    <Table.Tr>
                      <Table.Td colSpan={6}>
                        <Text size="sm" c="dimmed">
                          (không có)
                        </Text>
                      </Table.Td>
                    </Table.Tr>
                  ) : (
                    actors.map((actor) => (
                      <Table.Tr
                        key={`${actor.kind}:${actor.id}`}
                        className={classes.clickRow}
                        onClick={() => handleActorClick(actor)}
                      >
                        <Table.Td>{actor.rank}</Table.Td>
                        <Table.Td>
                          <Text size="sm" fw={600}>
                            {actor.name}
                          </Text>
                          {actor.evidence ? (
                            <Text size="xs" c="dimmed" lineClamp={1}>
                              {actor.evidence}
                            </Text>
                          ) : null}
                        </Table.Td>
                        <Table.Td>
                          <Badge size="sm" variant="light" color="gray">
                            {KIND_LABEL[actor.kind] || actor.kind}
                          </Badge>
                        </Table.Td>
                        <Table.Td>{actor.affected_count}</Table.Td>
                        <Table.Td>{actor.impact}</Table.Td>
                        <Table.Td>
                          <Text size="xs">{actor.suggestion}</Text>
                        </Table.Td>
                      </Table.Tr>
                    ))
                  )}
                </Table.Tbody>
              </Table>
            </ScrollArea.Autosize>
          </Box>

          <Box className={classes.panel}>
            <Group justify="space-between" mb="sm" wrap="wrap" gap="xs">
              <Text className={classes.panelTitle}>Phân tích</Text>
              <SegmentedControl
                size="xs"
                value={chartTab}
                onChange={setChartTab}
                data={CHART_TABS}
              />
            </Group>
            {chartTab === 'shap' && (
              <Alert color="blue" variant="light" title="SHAP (P1)">
                KernelSHAP Dual-Head chưa có trong P0. Actor ranking và bảng issue vẫn dùng được.
              </Alert>
            )}
            {chartTab === 'risk' && (
              <Stack gap="sm">
                <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                  Phân bố rủi ro (open)
                </Text>
                {(data.risk_distribution || []).map((bucket) => (
                  <div key={bucket.level}>
                    <Group justify="space-between" mb={4}>
                      <Text size="sm">{bucket.level}</Text>
                      <Text size="sm" fw={600}>
                        {bucket.count}
                      </Text>
                    </Group>
                    <div className={classes.barTrack}>
                      <div
                        className={classes.barFill}
                        data-level={bucket.level}
                        style={{ width: `${(100 * bucket.count) / maxRisk}%` }}
                      />
                    </div>
                  </div>
                ))}
              </Stack>
            )}
            {chartTab === 'deps' && (
              <Stack gap="xs">
                <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
                  Top blockers by fan-out
                </Text>
                {(data.top_blockers || []).length === 0 ? (
                  <Text size="sm" c="dimmed">
                    (không có)
                  </Text>
                ) : (
                  (data.top_blockers || []).map((b) => (
                    <UnstyledButton
                      key={b.key}
                      className={classes.depRow}
                      onClick={() => onSelectIssue(b.key)}
                    >
                      <Text size="sm" fw={600}>
                        {b.key}
                      </Text>
                      <Text size="xs" c="dimmed">
                        fan-out {b.fan_out} · impact {b.impact}
                      </Text>
                    </UnstyledButton>
                  ))
                )}
              </Stack>
            )}
          </Box>
        </div>

        {/* [D] Risky issues */}
        <Box className={classes.panel}>
          <Text className={classes.panelTitle} mb="sm">
            Issue rủi ro
          </Text>
          <ScrollArea type="auto">
            <Table highlightOnHover horizontalSpacing="sm" verticalSpacing={6} miw={720}>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>Key</Table.Th>
                  <Table.Th>Summary</Table.Th>
                  <Table.Th>Level</Table.Th>
                  <Table.Th>p_delay</Table.Th>
                  <Table.Th>Assignee</Table.Th>
                  <Table.Th>Blocked-by</Table.Th>
                  <Table.Th>Top SHAP</Table.Th>
                  <Table.Th>Deadline</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {filteredIssues.length === 0 ? (
                  <Table.Tr>
                    <Table.Td colSpan={8}>
                      <Text size="sm" c="dimmed">
                        (không có)
                      </Text>
                    </Table.Td>
                  </Table.Tr>
                ) : (
                  filteredIssues.map((row) => (
                    <Table.Tr
                      key={row.key}
                      className={classes.clickRow}
                      data-selected={selectedIssueKey === row.key ? 'true' : undefined}
                      onClick={() => onSelectIssue(row.key)}
                    >
                      <Table.Td>
                        <Text size="sm" fw={700}>
                          {row.key}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="sm" lineClamp={1} maw={240}>
                          {row.summary}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        {row.level ? (
                          <Badge size="sm" color={levelColor(row.level)} variant="filled">
                            {row.level}
                          </Badge>
                        ) : (
                          '—'
                        )}
                      </Table.Td>
                      <Table.Td>{formatPDelay(row.p_delay)}</Table.Td>
                      <Table.Td>
                        <Text size="sm">{row.assignee}</Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" lineClamp={1}>
                          {(row.blocked_by || []).join(', ') || '—'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" c="dimmed">
                          {row.top_shap_feature || '—'}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs">{row.deadline || row.duedate || '—'}</Text>
                      </Table.Td>
                    </Table.Tr>
                  ))
                )}
              </Table.Tbody>
            </Table>
          </ScrollArea>
        </Box>
      </Stack>

      <ExplainDrawer
        opened={Boolean(selectedIssueKey)}
        onClose={() => onSelectIssue(null)}
        explain={explain}
        onOpenBoard={onOpenBoard}
      />
    </Box>
  );
}
