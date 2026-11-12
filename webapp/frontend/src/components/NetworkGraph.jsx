import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActionIcon,
  Alert,
  Anchor,
  Badge,
  Box,
  Button,
  Card,
  Center,
  Checkbox,
  Collapse,
  Divider,
  Group,
  Loader,
  Paper,
  Progress,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  TextInput,
  ThemeIcon,
  Tooltip,
} from '@mantine/core';
import {
  IconAlertTriangle,
  IconArrowsSplit,
  IconCheck,
  IconChevronDown,
  IconChevronUp,
  IconClock,
  IconFlame,
  IconFocusCentered,
  IconInbox,
  IconLock,
  IconRefresh,
  IconRoute,
  IconSearch,
  IconTopologyStarRing3,
  IconUserExclamation,
  IconZoomIn,
  IconZoomOut,
} from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { DataSet, Network } from 'vis-network/standalone';
import { getDashboardGraph } from '../api/client';
import {
  FILTERS,
  RISK,
  UNASSIGNED,
  buildModel,
  buildScene,
  daysLeftText,
  drawOverlay,
  findTarget,
  issueInsight,
  laneAt,
  matchesSearch,
  overviewInsight,
  personInsight,
  riskOf,
} from './graphModel';

const BASE_OPTIONS = {
  autoResize: true,
  height: '100%',
  width: '100%',
  interaction: { hover: true, tooltipDelay: 100, zoomView: true, dragView: true, keyboard: false },
  nodes: { font: { face: 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif' } },
  edges: { arrows: { to: { scaleFactor: 0.7 } } },
};

const KPIS = [
  { filter: 'HIGH_RISK', color: 'red', icon: IconFlame, count: (s) => s.high_risk_count, label: 'Rủi ro cao' },
  { filter: 'OVERDUE', color: 'red', icon: IconClock, count: (s) => s.overdue_count, label: 'Quá hạn' },
  { filter: 'BOTTLENECK', color: 'red', icon: IconAlertTriangle, count: (s) => s.bottlenecks_count, label: 'Điểm nghẽn' },
  { filter: 'OVERLOADED', color: 'red', icon: IconUserExclamation, count: (s) => s.overloaded_count, label: 'Người quá tải' },
  { filter: 'UNASSIGNED', color: 'yellow', icon: IconInbox, count: (s) => s.unassigned_count, label: 'Chưa phân công' },
  { filter: 'BLOCKED', color: 'orange', icon: IconLock, count: (s) => s.blocked_count, label: 'Đang bị chặn' },
  { filter: 'CRITICAL', color: 'violet', icon: IconRoute, count: (s) => s.critical_count, label: 'Trọng yếu TGN' },
];

function frame(network, container, bounds, animation) {
  if (!bounds) {
    network.fit({ animation: false });
    network.moveTo({ scale: network.getScale() * 0.88, animation });
    return;
  }
  const width = bounds.maxX - bounds.minX;
  const height = bounds.maxY - bounds.minY;
  const scale = Math.min(container.clientWidth / width, 1) * 0.97;
  const visibleHeight = container.clientHeight / scale;
  const centerY = height <= visibleHeight ? (bounds.minY + bounds.maxY) / 2 : bounds.minY + visibleHeight / 2 - 10;
  network.moveTo({ position: { x: (bounds.minX + bounds.maxX) / 2, y: centerY }, scale, animation });
}

const isOverview = (view) => view.mode === 'lanes' || view.mode === 'dag';
const overviewOf = (view) => (isOverview(view) ? view.mode : view.back);

export default function NetworkGraph({ selectedProject = '', onSelectIssue, selectedIssueKey = null }) {
  const containerRef = useRef(null);
  const networkRef = useRef(null);
  const nodesRef = useRef(null);
  const handlersRef = useRef({});

  const [view, setView] = useState({ mode: 'lanes' });
  const [activeFilter, setActiveFilter] = useState('ALL');
  const [searchQuery, setSearchQuery] = useState('');
  const [showDone, setShowDone] = useState(false);
  const [showRelates, setShowRelates] = useState(false);
  const [dagLayout, setDagLayout] = useState('hierarchical_lr');
  const [hovered, setHovered] = useState(null);
  const [isLegendOpen, setIsLegendOpen] = useState(false);

  const { data: graphData, isLoading, isError, refetch, isFetching } = useQuery({
    queryKey: ['dashboard-graph', selectedProject],
    queryFn: () => getDashboardGraph(selectedProject || null),
    staleTime: 15000,
  });

  const model = useMemo(() => (graphData?.nodes?.length ? buildModel(graphData) : null), [graphData]);
  const summary = graphData?.summary || {};

  const go = (target) => {
    if (target.mode === 'focusIssue') {
      setView((v) => ({ mode: 'focusIssue', key: target.key, depth: v.mode === 'focusIssue' ? v.depth : 2, back: overviewOf(v) }));
      onSelectIssue?.(target.key);
    } else {
      setView((v) => ({ ...target, back: overviewOf(v) }));
    }
  };

  const validView = useMemo(() => {
    if (!model) return view;
    if (view.mode === 'focusIssue' && !model.issues.has(view.key)) return { mode: view.back };
    if (view.mode === 'focusPerson' && !model.people.has(view.id)) return { mode: view.back };
    return view;
  }, [model, view]);

  const scene = useMemo(
    () => model && buildScene(model, validView, { showDone, showRelates, dagLayout }),
    [model, validView, showDone, showRelates, dagLayout]
  );

  const dimmed = useMemo(() => {
    if (!model || !isOverview(validView)) return new Set();
    const match = FILTERS[activeFilter];
    return new Set(
      [...model.issues.values()]
        .filter((i) => !(match(i, model) && matchesSearch(model, i, searchQuery)))
        .map((i) => i.key)
    );
  }, [model, validView, activeFilter, searchQuery]);
  const dimmedRef = useRef(dimmed);
  dimmedRef.current = dimmed;

  handlersRef.current = {
    click: (params) => {
      const id = params.nodes[0];
      if (id && model.issues.has(id)) go({ mode: 'focusIssue', key: id });
      else if (id && model.people.has(id)) go({ mode: 'focusPerson', id });
      else if (!id) {
        const person = laneAt(scene.overlay, params.pointer.canvas);
        if (person) go({ mode: 'focusPerson', id: person.id });
      }
    },
    hover: (id) => {
      const issue = model?.issues.get(id);
      if (!issue) return;
      const pos = networkRef.current.canvasToDOM(networkRef.current.getPosition(id));
      setHovered({ issue, x: pos.x, y: pos.y });
    },
  };

  const prevSelected = useRef(selectedIssueKey);
  useEffect(() => {
    if (prevSelected.current === selectedIssueKey) return;
    prevSelected.current = selectedIssueKey;
    if (selectedIssueKey && model?.issues.has(selectedIssueKey) && !(view.mode === 'focusIssue' && view.key === selectedIssueKey)) {
      go({ mode: 'focusIssue', key: selectedIssueKey });
    }
  }, [selectedIssueKey, model]);

  useEffect(() => {
    if (!containerRef.current || !scene) return undefined;
    const withDim = (n) => (dimmedRef.current.has(n.id) ? { ...n, opacity: 0.2 } : n);
    const nodes = new DataSet(scene.nodes.map(withDim));
    nodesRef.current = nodes;
    const network = new Network(
      containerRef.current,
      { nodes, edges: new DataSet(scene.edges) },
      { ...BASE_OPTIONS, ...scene.options, edges: { ...BASE_OPTIONS.edges, ...scene.options.edges } }
    );
    networkRef.current = network;
    network.on('beforeDrawing', (ctx) => drawOverlay(ctx, scene.overlay));
    network.on('click', (params) => handlersRef.current.click(params));
    network.on('hoverNode', (params) => handlersRef.current.hover(params.node));
    network.on('blurNode', () => setHovered(null));
    network.on('dragStart', () => setHovered(null));
    frame(network, containerRef.current, scene.overlay.bounds, false);
    return () => {
      network.destroy();
      networkRef.current = null;
      nodesRef.current = null;
      setHovered(null);
    };
  }, [scene]);

  useEffect(() => {
    if (!nodesRef.current || !scene) return;
    nodesRef.current.update(
      scene.nodes.filter((n) => model.issues.has(n.id)).map((n) => ({ id: n.id, opacity: dimmed.has(n.id) ? 0.2 : n.baseOpacity }))
    );
  }, [dimmed]);

  const camera = {
    fit: () =>
      networkRef.current &&
      frame(networkRef.current, containerRef.current, scene?.overlay.bounds, { duration: 500, easingFunction: 'easeInOutQuad' }),
    zoom: (factor) =>
      networkRef.current?.moveTo({
        scale: networkRef.current.getScale() * factor,
        animation: { duration: 300, easingFunction: 'easeInOutQuad' },
      }),
  };

  const handleSearchSubmit = (e) => {
    e.preventDefault();
    const target = model && findTarget(model, searchQuery);
    if (target) go(target);
  };

  const toggleFilter = (filter) => {
    setActiveFilter((prev) => (prev === filter ? 'ALL' : filter));
    if (!isOverview(validView)) setView({ mode: validView.back });
  };

  return (
    <Card withBorder radius="md" padding="md" shadow="sm" style={{ position: 'relative', minHeight: 650 }}>
      <Stack gap="sm">
        <Group justify="space-between" align="center" wrap="wrap">
          <Group gap="xs">
            <ThemeIcon size="lg" radius="md" color="indigo" variant="light">
              <IconTopologyStarRing3 size={22} stroke={1.5} />
            </ThemeIcon>
            <Box>
              <Group gap="xs">
                <Text fw={700} size="md">Đồ thị phụ thuộc</Text>
                <Badge size="sm" variant="filled" color="indigo">{summary.total_nodes || 0} Tasks</Badge>
                <Badge size="sm" variant="light" color="gray">{summary.total_edges || 0} liên kết</Badge>
              </Group>
              <Text size="xs" c="dimmed">Task nào sắp trễ, ai đang ôm, bị chặn bởi đâu và trễ sẽ lan sang đâu</Text>
            </Box>
          </Group>
          <Group gap={6}>
            <Tooltip label="Canh giữa toàn màn hình" withArrow position="bottom">
              <ActionIcon variant="default" size="md" onClick={camera.fit} aria-label="Fit view">
                <IconFocusCentered size={17} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Phóng to" withArrow position="bottom">
              <ActionIcon variant="default" size="md" onClick={() => camera.zoom(1.3)} aria-label="Zoom in">
                <IconZoomIn size={17} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Thu nhỏ" withArrow position="bottom">
              <ActionIcon variant="default" size="md" onClick={() => camera.zoom(0.7)} aria-label="Zoom out">
                <IconZoomOut size={17} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Làm mới dữ liệu đồ thị" withArrow position="bottom">
              <ActionIcon variant="default" size="md" loading={isFetching} onClick={() => refetch()} aria-label="Refresh graph">
                <IconRefresh size={17} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>

        <Group gap="xs" wrap="wrap">
          {KPIS.map(({ filter, color, icon: Icon, count, label }) => (
            <Badge
              key={filter}
              size="md"
              variant={activeFilter === filter ? 'filled' : 'light'}
              color={color}
              leftSection={<Icon size={14} />}
              style={{ cursor: 'pointer' }}
              onClick={() => toggleFilter(filter)}
            >
              {count(summary) || 0} {label}
            </Badge>
          ))}
          <Badge size="md" variant="light" color="gray" leftSection={<IconCheck size={14} />}>
            {summary.done_count || 0} Đã hoàn thành
          </Badge>
        </Group>

        {isOverview(validView) ? (
          <Group justify="space-between" align="center" wrap="wrap" gap="xs">
            <Group gap="md" wrap="wrap">
              <Switch
                size="sm"
                label="Gom theo người phụ trách"
                checked={validView.mode === 'lanes'}
                onChange={(e) => setView({ mode: e.currentTarget.checked ? 'lanes' : 'dag' })}
              />
              <Checkbox size="xs" label="Hiện Relate / Duplicate" checked={showRelates} onChange={(e) => setShowRelates(e.currentTarget.checked)} />
              <Checkbox size="xs" label="Hiện task đã xong" checked={showDone} onChange={(e) => setShowDone(e.currentTarget.checked)} />
              {validView.mode === 'dag' && (
                <SegmentedControl
                  size="xs"
                  value={dagLayout}
                  onChange={setDagLayout}
                  data={[
                    { label: 'Lực liên kết', value: 'physics' },
                    { label: 'Trái → Phải', value: 'hierarchical_lr' },
                    { label: 'Trên → Dưới', value: 'hierarchical_ud' },
                  ]}
                />
              )}
            </Group>
            <Group gap="xs">
              <form onSubmit={handleSearchSubmit} style={{ width: 200 }}>
                <TextInput
                  size="xs"
                  placeholder="Tìm issue / người…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  rightSection={
                    <ActionIcon size="xs" variant="subtle" type="submit" aria-label="Search">
                      <IconSearch size={13} />
                    </ActionIcon>
                  }
                />
              </form>
              <Button
                size="xs"
                variant="subtle"
                color="gray"
                rightSection={isLegendOpen ? <IconChevronUp size={14} /> : <IconChevronDown size={14} />}
                onClick={() => setIsLegendOpen((v) => !v)}
              >
                Chú giải
              </Button>
            </Group>
          </Group>
        ) : (
          <Breadcrumb model={model} view={validView} onBack={() => setView({ mode: validView.back })} onDepth={(depth) => setView({ ...validView, depth })} />
        )}

        <Collapse in={isLegendOpen}>
          <Paper withBorder p="xs" radius="sm" bg="var(--mantine-color-gray-0)">
            <Group gap="md" wrap="wrap">
              {['HIGH', 'MED', 'LOW', 'DONE'].map((r) => (
                <Badge key={r} size="sm" variant="outline" style={{ background: RISK[r].fill, color: RISK[r].border, borderColor: RISK[r].border }}>
                  {r === 'DONE' ? 'Đã xong' : `Rủi ro ${RISK[r].label}`}
                </Badge>
              ))}
              <Text size="xs">━▶ Chặn</Text>
              <Text size="xs" c="red">━▶ đang lan trễ</Text>
              <Text size="xs" fw={700}>━━ đường găng ★</Text>
              <Text size="xs">viền nét đứt = quá hạn (+Nd) · ⛔ bị chặn · ↻ mở lại</Text>
              <Text size="xs">◯ người (viền đỏ = quá tải) · ⬡ sprint/version · ┄ phụ trách</Text>
            </Group>
          </Paper>
        </Collapse>

        <Group align="stretch" gap="sm" wrap="wrap">
          <Box
            style={{
              position: 'relative',
              flex: '1 1 420px',
              height: 560,
              borderRadius: 8,
              border: '1px solid var(--mantine-color-gray-3)',
              backgroundColor: '#ffffff',
              overflow: 'hidden',
            }}
          >
            {isLoading && (
              <Center h="100%">
                <Stack align="center" gap="xs">
                  <Loader size="md" type="dots" />
                  <Text size="sm" c="dimmed">Đang tải đồ thị phụ thuộc...</Text>
                </Stack>
              </Center>
            )}
            {isError && (
              <Center h="100%">
                <Alert icon={<IconAlertTriangle size={18} />} color="red" title="Lỗi tải đồ thị">
                  Không thể tải dữ liệu đồ thị của dự án. Vui lòng thử lại.
                </Alert>
              </Center>
            )}
            {!isLoading && !isError && !model && (
              <Center h="100%">
                <Stack align="center" gap="xs">
                  <ThemeIcon size="xl" radius="xl" color="gray" variant="light">
                    <IconArrowsSplit size={26} />
                  </ThemeIcon>
                  <Text fw={600} size="sm">Chưa có issue nào để vẽ</Text>
                </Stack>
              </Center>
            )}
            <div ref={containerRef} style={{ width: '100%', height: '100%', display: model ? 'block' : 'none' }} />
            {model && (
              <Box
                style={{
                  position: 'absolute',
                  bottom: 8,
                  left: 10,
                  pointerEvents: 'none',
                  backgroundColor: 'rgba(255,255,255,0.88)',
                  padding: '3px 8px',
                  borderRadius: 6,
                  border: '1px solid #e9ecef',
                }}
              >
                <Text size="xs" c="dimmed">{HINTS[validView.mode]}</Text>
              </Box>
            )}
            {hovered && <IssueTooltip model={model} hovered={hovered} />}
          </Box>

          {model && (
            <Paper withBorder radius="md" p="sm" style={{ flex: '1 1 260px', maxWidth: 360, height: 560, overflowY: 'auto' }}>
              <InsightPanel model={model} view={validView} go={go} />
            </Paper>
          )}
        </Group>
      </Stack>
    </Card>
  );
}

const HINTS = {
  lanes: 'Mỗi làn là một người. Làn đỏ = quá tải, làn vàng = chưa phân công. Bấm task hoặc tên người để xem tâm điểm.',
  dag: 'Cột = độ sâu trong chuỗi chặn (trái chặn phải). Bấm task để xem tâm điểm.',
  focusIssue: 'Đọc trái → phải: nguyên nhân → task này → hậu quả. Bấm node khác để dời tâm điểm.',
  focusPerson: 'Bấm một task để xem chuỗi phụ thuộc của nó.',
};

function Breadcrumb({ model, view, onBack, onDepth }) {
  const title = view.mode === 'focusIssue' ? view.key : model?.people.get(view.id)?.name;
  return (
    <Group gap="sm" align="center">
      <Anchor size="sm" onClick={onBack}>← Tổng quan</Anchor>
      <Text size="sm" c="dimmed">/</Text>
      <Text size="sm" fw={700}>{title}</Text>
      {view.mode === 'focusIssue' && (
        <Group gap={6} ml="md">
          <Text size="xs" c="dimmed">Độ sâu</Text>
          <SegmentedControl
            size="xs"
            value={String(view.depth)}
            onChange={(d) => onDepth(Number(d))}
            data={['1', '2', '3']}
          />
        </Group>
      )}
    </Group>
  );
}

function RiskBadge({ issue }) {
  const r = RISK[riskOf(issue)];
  return (
    <Badge size="sm" variant="outline" style={{ background: r.fill, color: r.border, borderColor: r.border }}>
      {riskOf(issue) === 'DONE' ? 'Đã xong' : `Rủi ro ${r.label}`}
    </Badge>
  );
}

function Section({ title, children }) {
  return (
    <Stack gap={4}>
      <Text size="xs" fw={700} c="dimmed" tt="uppercase">{title}</Text>
      {children}
    </Stack>
  );
}

function Row({ label, children }) {
  return (
    <Group justify="space-between" gap="xs" wrap="nowrap">
      <Text size="xs" c="dimmed">{label}</Text>
      <Text size="xs" fw={500} ta="right">{children}</Text>
    </Group>
  );
}

function InsightPanel({ model, view, go }) {
  if (view.mode === 'focusIssue') return <IssueInsight model={model} insight={issueInsight(model, view.key)} go={go} />;
  if (view.mode === 'focusPerson') return <PersonInsight model={model} insight={personInsight(model, view.id)} go={go} />;
  return <OverviewInsight model={model} insight={overviewInsight(model)} go={go} />;
}

function OverviewInsight({ model, insight, go }) {
  return (
    <Stack gap="sm">
      <Section title="Cần chú ý hôm nay">
        {insight.bottlenecks.length === 0 && <Text size="xs" c="dimmed">Không có điểm nghẽn.</Text>}
        {insight.bottlenecks.map(({ issue, impact }) => (
          <Button
            key={issue.key}
            variant="default"
            size="compact-sm"
            justify="space-between"
            fullWidth
            onClick={() => go({ mode: 'focusIssue', key: issue.key })}
            rightSection={<Text size="xs" c="dimmed">kéo theo {impact}</Text>}
          >
            <Text size="xs" fw={700} c={RISK[riskOf(issue)].border}>{issue.key}</Text>
          </Button>
        ))}
      </Section>
      <Section title="Đường găng">
        <Text size="xs">{insight.criticalPath.join(' → ') || '—'}</Text>
      </Section>
      <Divider />
      <Section title="Người phụ trách">
        {model.peopleOrder.map((pid) => {
          const p = model.people.get(pid);
          return (
            <Button
              key={pid}
              variant="subtle"
              size="compact-sm"
              color={p.kind === 'unassigned' ? 'yellow' : p.is_overloaded ? 'red' : 'gray'}
              justify="space-between"
              fullWidth
              onClick={() => go({ mode: 'focusPerson', id: pid })}
              rightSection={
                <Text size="xs" c="dimmed">
                  {p.open_count} mở · {p.high_risk_count} cao{p.is_overloaded ? ' · quá tải' : ''}
                </Text>
              }
            >
              <Text size="xs" fw={600}>{p.kind === 'unassigned' ? '📥 ' : ''}{p.name}</Text>
            </Button>
          );
        })}
      </Section>
    </Stack>
  );
}

function IssueInsight({ model, insight, go }) {
  const { issue, owner, deadlines, factors, down, downHigh, otherDeadlines, suggestions } = insight;
  return (
    <Stack gap="sm">
      <Stack gap={4}>
        <Text fw={700} size="sm">{issue.key} · {issue.summary}</Text>
        <Group gap={4}>
          <RiskBadge issue={issue} />
          {issue.is_overdue && <Badge size="sm" color="red" variant="light">Quá hạn {issue.overdue_days} ngày</Badge>}
          {issue.reopen_count > 0 && <Badge size="sm" color="grape" variant="light">Mở lại {issue.reopen_count} lần</Badge>}
        </Group>
      </Stack>
      <Stack gap={2}>
        <Row label="Xác suất trễ">{Math.round((issue.delay_value || 0) * 100)}%</Row>
        <Row label="Hạn">
          {deadlines.length ? deadlines.map((d) => `${d.name} (${daysLeftText(d)})`).join(', ') : issue.duedate || '—'}
        </Row>
        <Row label="Trạng thái">{issue.status || '—'}</Row>
        <Row label="Phụ trách">
          <Anchor size="xs" onClick={() => go({ mode: 'focusPerson', id: owner.id })}>{owner.name}</Anchor>
          {owner.is_overloaded && <Text span size="xs" c="red"> · quá tải</Text>}
        </Row>
        <Row label="Bị chặn bởi">{model.blockedBy.get(issue.key).join(', ') || '—'}</Row>
        <Row label="Đang chặn">{model.blocks.get(issue.key).join(', ') || '—'}</Row>
      </Stack>
      <Section title="Vì sao rủi ro">
        {factors.length ? factors.map((f) => <Text key={f} size="xs">• {f}</Text>) : <Text size="xs" c="dimmed">Không có yếu tố nổi bật</Text>}
      </Section>
      <Section title="Ảnh hưởng">
        <Text size="xs">
          Kéo theo <b>{down.length}</b> task ({downHigh} rủi ro cao)
          {otherDeadlines.length > 0 && <>, lan sang <b>{otherDeadlines.map((d) => d.name).join(', ')}</b></>}.
        </Text>
      </Section>
      <Section title="Gợi ý">
        {suggestions.length === 0 && <Text size="xs" c="dimmed">Không có hành động cần làm ngay.</Text>}
        {suggestions.map((s) =>
          s.view ? (
            <Button key={s.text} variant="light" size="compact-sm" justify="flex-start" fullWidth onClick={() => go(s.view)}>
              {s.text}
            </Button>
          ) : (
            <Text key={s.text} size="xs">• {s.text}</Text>
          )
        )}
      </Section>
    </Stack>
  );
}

function PersonInsight({ model, insight, go }) {
  const { person, mine, blockingOthers, candidates, movable } = insight;
  const unassigned = person.id === UNASSIGNED;
  const target = candidates[0];
  return (
    <Stack gap="sm">
      <Stack gap={4}>
        <Text fw={700} size="sm">{unassigned ? '📥 ' : ''}{person.name}</Text>
        <Group gap={4}>
          {person.is_overloaded && <Badge size="sm" color="red" variant="light">Quá tải</Badge>}
          {unassigned && <Badge size="sm" color="yellow" variant="light">Hàng đợi triage</Badge>}
          {!unassigned && !person.is_overloaded && <Badge size="sm" color="gray" variant="light">Bình thường</Badge>}
        </Group>
      </Stack>
      <Stack gap={2}>
        <Row label="Task mở">
          {person.open_count}
          {!unassigned && ` (ngưỡng p90 = ${model.threshold})`}
        </Row>
        <Row label="Rủi ro cao">{person.high_risk_count}</Row>
        <Row label="Quá hạn">{person.overdue_count}</Row>
      </Stack>
      <Section title="Đang chặn người khác">
        {blockingOthers.length === 0 && <Text size="xs" c="dimmed">Không</Text>}
        {blockingOthers.map((b) => (
          <Text key={b.key} size="xs">
            • <Anchor size="xs" onClick={() => go({ mode: 'focusIssue', key: b.key })}>{b.key}</Anchor> →{' '}
            {b.targets.map((t) => `${t.key} (${t.owner})`).join(', ')}
          </Text>
        ))}
      </Section>
      {unassigned && target && (
        <Section title="Gợi ý giao việc">
          {mine.map((i) => (
            <Text key={i.key} size="xs">• Giao {i.key} cho {target.name} ({target.open_count} mở)</Text>
          ))}
        </Section>
      )}
      {person.is_overloaded && (
        <Section title="Người có thể nhận bớt">
          {candidates.map((c) => (
            <Anchor key={c.id} size="xs" onClick={() => go({ mode: 'focusPerson', id: c.id })}>
              {c.name} ({c.open_count} mở · {c.high_risk_count} cao)
            </Anchor>
          ))}
          {target && movable.map((i) => <Text key={i.key} size="xs">• Chuyển {i.key} cho {target.name}</Text>)}
        </Section>
      )}
    </Stack>
  );
}

function IssueTooltip({ model, hovered }) {
  const { issue, x, y } = hovered;
  const owner = model.people.get(issue.person_id);
  return (
    <Paper
      shadow="md"
      withBorder
      p="sm"
      radius="md"
      style={{
        position: 'absolute',
        top: Math.max(10, Math.min(y - 120, 330)),
        left: Math.max(10, x + 20),
        zIndex: 100,
        width: 300,
        pointerEvents: 'none',
      }}
    >
      <Stack gap={6}>
        <Group justify="space-between" wrap="nowrap">
          <Text fw={700} size="sm">{issue.key}</Text>
          <RiskBadge issue={issue} />
        </Group>
        <Text size="xs" lineClamp={2} fw={500}>{issue.summary}</Text>
        <Divider />
        <Row label="Phụ trách">{owner.name}{owner.is_overloaded ? ' · quá tải' : ''}</Row>
        <Row label="Hạn chót">{issue.is_overdue ? `Quá hạn ${issue.overdue_days} ngày` : issue.duedate || 'Chưa đặt'}</Row>
        <Box>
          <Row label="Xác suất trễ">{Math.round((issue.delay_value || 0) * 100)}%</Row>
          <Progress value={(issue.delay_value || 0) * 100} size="xs" color={issue.delay_value >= 0.5 ? 'red' : 'blue'} radius="xl" />
        </Box>
        <Row label="Chặn / bị chặn">{issue.blocks_count} / {issue.blocked_by_count}</Row>
        {issue.reopen_count > 0 && <Row label="Mở lại">{issue.reopen_count} lần</Row>}
      </Stack>
    </Paper>
  );
}
