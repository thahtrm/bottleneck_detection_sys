import React, { useEffect, useRef, useState, useMemo, useCallback } from 'react';
import {
  Card,
  Group,
  Stack,
  Text,
  Badge,
  Button,
  ActionIcon,
  Tooltip,
  ThemeIcon,
  TextInput,
  SegmentedControl,
  Paper,
  Box,
  Center,
  Loader,
  Alert,
  Divider,
  Progress,
  Collapse,
} from '@mantine/core';
import {
  IconSearch,
  IconZoomIn,
  IconZoomOut,
  IconFocusCentered,
  IconRefresh,
  IconAlertTriangle,
  IconClock,
  IconLock,
  IconFlame,
  IconRoute,
  IconCheck,
  IconFilter,
  IconInfoCircle,
  IconChevronDown,
  IconChevronUp,
  IconArrowsSplit,
  IconPlayerPlay,
  IconPlayerPause,
  IconTopologyStarRing3,
} from '@tabler/icons-react';
import { useQuery } from '@tanstack/react-query';
import { Network, DataSet } from 'vis-network/standalone';
import { getDashboardGraph } from '../api/client';

/**
 * Bảng màu chuẩn cho các trạng thái rủi ro trên đồ thị
 */
const COLOR_PALETTE = {
  bottleneck: {
    background: '#e03131',
    border: '#c92a2a',
    highlight: { background: '#f03e3e', border: '#a61e4d' },
    font: '#ffffff',
    glow: 'rgba(224, 49, 49, 0.45)',
  },
  overdue: {
    background: '#fa5252',
    border: '#e03131',
    highlight: { background: '#ff6b6b', border: '#c92a2a' },
    font: '#ffffff',
    glow: 'rgba(250, 82, 82, 0.4)',
  },
  critical: {
    background: '#7950f2',
    border: '#5f3dc4',
    highlight: { background: '#845ef7', border: '#4c1d95' },
    font: '#ffffff',
    glow: 'rgba(121, 80, 242, 0.4)',
  },
  blocked: {
    background: '#fd7e14',
    border: '#d9480f',
    highlight: { background: '#ff922b', border: '#b23608' },
    font: '#ffffff',
    glow: 'rgba(253, 126, 20, 0.35)',
  },
  highRisk: {
    background: '#f76707',
    border: '#d9480f',
    highlight: { background: '#ff8736', border: '#d9480f' },
    font: '#ffffff',
    glow: 'rgba(247, 103, 7, 0.35)',
  },
  medRisk: {
    background: '#fab005',
    border: '#f59f00',
    highlight: { background: '#ffd43b', border: '#e67700' },
    font: '#212529',
    glow: 'rgba(250, 176, 5, 0.3)',
  },
  normal: {
    background: '#228be6',
    border: '#1971c2',
    highlight: { background: '#339af0', border: '#1864ab' },
    font: '#ffffff',
    glow: 'rgba(34, 139, 230, 0.25)',
  },
  done: {
    background: '#40c057',
    border: '#2f9e44',
    highlight: { background: '#51cf66', border: '#2b8a3e' },
    font: '#ffffff',
    glow: 'rgba(64, 192, 87, 0.25)',
  },
  dimmed: {
    background: '#e9ecef',
    border: '#ced4da',
    highlight: { background: '#dee2e6', border: '#adb5bd' },
    font: '#868e96',
    glow: 'none',
  },
};

/**
 * Xác định phân loại màu chính cho từng node
 */
function getNodeTheme(node) {
  if (node.status_category === 'done') return COLOR_PALETTE.done;
  if (node.is_bottleneck) return COLOR_PALETTE.bottleneck;
  if (node.is_overdue) return COLOR_PALETTE.overdue;
  if (node.blocked) return COLOR_PALETTE.blocked;
  if (node.is_critical) return COLOR_PALETTE.critical;
  if (node.level === 'HIGH') return COLOR_PALETTE.highRisk;
  if (node.level === 'MED') return COLOR_PALETTE.medRisk;
  return COLOR_PALETTE.normal;
}

export default function NetworkGraph({
  selectedProject = '',
  onSelectIssue,
  selectedIssueKey = null,
}) {
  const containerRef = useRef(null);
  const networkRef = useRef(null);
  const nodesDataSetRef = useRef(null);
  const edgesDataSetRef = useRef(null);

  // Trạng thái giao diện
  const [activeFilter, setActiveFilter] = useState('ALL'); // ALL, BOTTLENECK, OVERDUE, BLOCKED, CRITICAL, HIGH_RISK
  const [layoutMode, setLayoutMode] = useState('physics'); // 'physics' | 'hierarchical_lr' | 'hierarchical_ud'
  const [physicsEnabled, setPhysicsEnabled] = useState(true);
  const [searchQuery, setSearchQuery] = useState('');
  const [hoveredNodeData, setHoveredNodeData] = useState(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [isLegendOpen, setIsLegendOpen] = useState(false);

  // Lấy dữ liệu đồ thị từ API
  const {
    data: graphData,
    isLoading,
    isError,
    refetch,
    isFetching,
  } = useQuery({
    queryKey: ['dashboard-graph', selectedProject],
    queryFn: () => getDashboardGraph(selectedProject || null),
    staleTime: 15000,
  });

  const summary = graphData?.summary || {
    total_nodes: 0,
    total_edges: 0,
    bottlenecks_count: 0,
    overdue_count: 0,
    high_risk_count: 0,
    blocked_count: 0,
    critical_count: 0,
    done_count: 0,
  };

  // Node Map để truy vấn nhanh
  const nodeMap = useMemo(() => {
    const map = new Map();
    (graphData?.nodes || []).forEach((n) => map.set(n.id, n));
    return map;
  }, [graphData]);

  // Tìm kiếm danh sách lân cận (Upstream & Downstream)
  const adjacency = useMemo(() => {
    const upstream = new Map(); // target -> [sources that block it]
    const downstream = new Map(); // source -> [targets that are blocked by it]
    (graphData?.nodes || []).forEach((n) => {
      upstream.set(n.id, new Set());
      downstream.set(n.id, new Set());
    });
    (graphData?.edges || []).forEach((e) => {
      if (downstream.has(e.from)) downstream.get(e.from).add(e.to);
      if (upstream.has(e.to)) upstream.get(e.to).add(e.from);
    });
    return { upstream, downstream };
  }, [graphData]);

  /**
   * Tạo cấu hình options cho Vis Network
   */
  const getNetworkOptions = useCallback(
    (mode, physicsOn) => {
      const isHierarchical = mode.startsWith('hierarchical');
      const direction = mode === 'hierarchical_ud' ? 'UD' : 'LR';

      return {
        autoResize: true,
        height: '100%',
        width: '100%',
        layout: {
          randomSeed: 42,
          hierarchical: isHierarchical
            ? {
                enabled: true,
                direction,
                sortMethod: 'directed',
                levelSeparation: 190,
                nodeSpacing: 130,
                treeSpacing: 180,
                blockShifting: true,
                edgeMinimization: true,
                parentCentralization: true,
              }
            : { enabled: false },
        },
        interaction: {
          hover: true,
          hoverConnectedEdges: true,
          selectConnectedEdges: true,
          multiselect: false,
          tooltipDelay: 100,
          navigationButtons: false,
          keyboard: false,
          zoomView: true,
          dragView: true,
        },
        physics: isHierarchical
          ? false
          : {
              enabled: physicsOn,
              solver: 'forceAtlas2Based',
              forceAtlas2Based: {
                gravitationalConstant: -48,
                centralGravity: 0.007,
                springLength: 130,
                springConstant: 0.08,
                damping: 0.5,
                avoidOverlap: 0.8,
              },
              stabilization: {
                enabled: true,
                iterations: 150,
                updateInterval: 25,
                fit: true,
              },
            },
        nodes: {
          shape: 'box',
          margin: { top: 9, right: 14, bottom: 9, left: 14 },
          font: {
            size: 13,
            face: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
            bold: { color: '#ffffff', size: 13 },
            multi: 'html',
          },
          borderWidth: 2,
          shadow: {
            enabled: true,
            color: 'rgba(0,0,0,0.12)',
            size: 8,
            x: 2,
            y: 3,
          },
        },
        edges: {
          width: 2,
          arrows: {
            to: {
              enabled: true,
              scaleFactor: 0.85,
              type: 'arrow',
            },
          },
          smooth: {
            enabled: true,
            type: isHierarchical ? 'cubicBezier' : 'continuous',
            roundness: 0.25,
          },
          font: {
            size: 10,
            align: 'top',
            background: 'rgba(255, 255, 255, 0.85)',
            strokeWidth: 0,
          },
        },
      };
    },
    []
  );

  /**
   * Biến đổi dữ liệu node từ API sang format Vis DataSet
   */
  const buildVisData = useCallback(
    (focusKey = null, filterMode = 'ALL') => {
      if (!graphData) return { visNodes: [], visEdges: [] };

      // Tập hợp các node cần làm nổi bật theo filterMode
      let highlightedKeySet = null;
      if (filterMode === 'BOTTLENECK') {
        highlightedKeySet = new Set(
          graphData.nodes.filter((n) => n.is_bottleneck).map((n) => n.id)
        );
      } else if (filterMode === 'OVERDUE') {
        highlightedKeySet = new Set(
          graphData.nodes.filter((n) => n.is_overdue).map((n) => n.id)
        );
      } else if (filterMode === 'BLOCKED') {
        highlightedKeySet = new Set(
          graphData.nodes.filter((n) => n.blocked).map((n) => n.id)
        );
      } else if (filterMode === 'CRITICAL') {
        highlightedKeySet = new Set(
          graphData.nodes.filter((n) => n.is_critical || n.is_critical_path).map((n) => n.id)
        );
      } else if (filterMode === 'HIGH_RISK') {
        highlightedKeySet = new Set(
          graphData.nodes.filter((n) => n.level === 'HIGH').map((n) => n.id)
        );
      }

      // Nếu đang click chọn 1 node cụ thể, tạo tập liên thông (upstream + downstream)
      let focusedSubgraphSet = null;
      if (focusKey && nodeMap.has(focusKey)) {
        focusedSubgraphSet = new Set([focusKey]);
        const up = adjacency.upstream.get(focusKey) || new Set();
        const down = adjacency.downstream.get(focusKey) || new Set();
        up.forEach((k) => focusedSubgraphSet.add(k));
        down.forEach((k) => focusedSubgraphSet.add(k));
      }

      // Xây dựng visNodes
      const visNodes = graphData.nodes.map((node) => {
        const theme = getNodeTheme(node);
        const isFocused = focusKey === node.id;
        const inSubgraph = focusedSubgraphSet ? focusedSubgraphSet.has(node.id) : true;
        const matchesFilter = highlightedKeySet ? highlightedKeySet.has(node.id) : true;

        const isDimmed =
          (focusedSubgraphSet && !inSubgraph) || (highlightedKeySet && !matchesFilter);

        // Biểu tượng trạng thái đi kèm
        let badgeIcon = '';
        if (node.is_bottleneck) badgeIcon = '🚨 ';
        else if (node.is_overdue) badgeIcon = '⏰ ';
        else if (node.blocked) badgeIcon = '⛓️ ';
        else if (node.is_critical) badgeIcon = '🟣 ';
        else if (node.status_category === 'done') badgeIcon = '✓ ';

        // Tóm tắt ngắn gọn
        const shortSummary =
          node.summary && node.summary.length > 24
            ? `${node.summary.slice(0, 22)}...`
            : node.summary || '';

        const label = `<b>${badgeIcon}${node.key}</b>\n${shortSummary}`;

        const nodeColor = isDimmed
          ? {
              background: '#f1f3f5',
              border: '#dee2e6',
              highlight: { background: '#e9ecef', border: '#ced4da' },
            }
          : {
              background: theme.background,
              border: isFocused ? '#1864ab' : theme.border,
              highlight: theme.highlight,
            };

        const fontColor = isDimmed ? '#adb5bd' : theme.font;

        return {
          id: node.id,
          label,
          shape: node.is_bottleneck ? 'box' : 'box',
          color: nodeColor,
          font: {
            color: fontColor,
            size: node.is_bottleneck ? 14 : 12,
            bold: { color: fontColor },
          },
          borderWidth: isFocused ? 4 : node.is_bottleneck || node.is_overdue ? 3 : 2,
          shadow: isDimmed
            ? false
            : {
                enabled: true,
                color: isFocused ? 'rgba(34, 139, 230, 0.6)' : theme.glow,
                size: isFocused ? 18 : 10,
                x: 0,
                y: 2,
              },
          opacity: isDimmed ? 0.35 : 1.0,
        };
      });

      // Xây dựng visEdges
      const visEdges = graphData.edges.map((edge) => {
        const inFocusedPath =
          focusedSubgraphSet &&
          focusedSubgraphSet.has(edge.from) &&
          focusedSubgraphSet.has(edge.to);

        const isDimmed =
          (focusedSubgraphSet && !inFocusedPath) ||
          (highlightedKeySet &&
            (!highlightedKeySet.has(edge.from) && !highlightedKeySet.has(edge.to)));

        let color = '#ced4da';
        let width = 1.8;
        let dashes = false;

        if (edge.is_critical_path) {
          color = '#7950f2';
          width = 3.5;
          dashes = [5, 4];
        } else if (edge.is_bottleneck_edge) {
          color = '#e03131';
          width = 3;
        } else if (edge.is_overdue_edge) {
          color = '#fa5252';
          width = 2.8;
        } else if (edge.is_blocking) {
          color = '#fd7e14';
          width = 2.4;
        }

        if (inFocusedPath) {
          color = '#228be6';
          width = 3.8;
        }

        return {
          id: edge.id,
          from: edge.from,
          to: edge.to,
          label: isDimmed ? '' : edge.label,
          color: {
            color: isDimmed ? '#e9ecef' : color,
            highlight: '#1864ab',
            hover: color,
            opacity: isDimmed ? 0.15 : 0.95,
          },
          width: isDimmed ? 1 : width,
          dashes,
          arrows: {
            to: {
              enabled: true,
              scaleFactor: isDimmed ? 0.5 : 0.85,
            },
          },
        };
      });

      return { visNodes, visEdges };
    },
    [graphData, nodeMap, adjacency]
  );

  /**
   * Khởi tạo Vis Network instance
   */
  useEffect(() => {
    if (!containerRef.current || !graphData || graphData.nodes.length === 0) {
      return;
    }

    const { visNodes, visEdges } = buildVisData(selectedIssueKey, activeFilter);
    const nodesDataSet = new DataSet(visNodes);
    const edgesDataSet = new DataSet(visEdges);

    nodesDataSetRef.current = nodesDataSet;
    edgesDataSetRef.current = edgesDataSet;

    const data = { nodes: nodesDataSet, edges: edgesDataSet };
    const options = getNetworkOptions(layoutMode, physicsEnabled);

    const network = new Network(containerRef.current, data, options);
    networkRef.current = network;

    // Lắng nghe sự kiện Click vào node
    network.on('click', (params) => {
      if (params.nodes && params.nodes.length > 0) {
        const clickedKey = params.nodes[0];
        if (onSelectIssue) onSelectIssue(clickedKey);

        // Zoom nhẹ nhàng đến node được chọn
        network.focus(clickedKey, {
          scale: 1.25,
          animation: { duration: 600, easingFunction: 'easeInOutQuad' },
        });
      } else {
        // Click ra khoảng trắng canvas -> Bỏ chọn
        if (onSelectIssue) onSelectIssue(null);
      }
    });

    // Lắng nghe sự kiện Hover node -> hiển thị Tooltip thông tin
    network.on('hoverNode', (params) => {
      const nodeKey = params.node;
      const rawNode = nodeMap.get(nodeKey);
      if (rawNode) {
        const domPos = network.canvasToDOM(network.getPosition(nodeKey));
        setHoveredNodeData(rawNode);
        setTooltipPos({ x: domPos.x, y: domPos.y });
      }
    });

    network.on('blurNode', () => {
      setHoveredNodeData(null);
    });

    return () => {
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    };
  }, [graphData, layoutMode]);

  /**
   * Cập nhật màu sắc & highlight khi thay đổi selectedIssueKey hoặc activeFilter
   */
  useEffect(() => {
    if (!nodesDataSetRef.current || !edgesDataSetRef.current || !graphData) return;

    const { visNodes, visEdges } = buildVisData(selectedIssueKey, activeFilter);
    nodesDataSetRef.current.update(visNodes);
    edgesDataSetRef.current.update(visEdges);

    // Nếu có selectedIssueKey, focus camera vào node đó
    if (selectedIssueKey && networkRef.current && nodeMap.has(selectedIssueKey)) {
      networkRef.current.focus(selectedIssueKey, {
        scale: 1.2,
        animation: { duration: 500, easingFunction: 'easeInOutQuad' },
      });
    }
  }, [selectedIssueKey, activeFilter, buildVisData, graphData, nodeMap]);

  /**
   * Xử lý bật/tắt hiệu ứng physics
   */
  const handleTogglePhysics = () => {
    const nextState = !physicsEnabled;
    setPhysicsEnabled(nextState);
    if (networkRef.current) {
      networkRef.current.setOptions({ physics: { enabled: nextState } });
    }
  };

  /**
   * Xử lý chuyển đổi layout: Lực liên kết vs Cây phân cấp
   */
  const handleChangeLayout = (newMode) => {
    setLayoutMode(newMode);
    if (networkRef.current) {
      const isHierarchical = newMode.startsWith('hierarchical');
      const nextPhysics = isHierarchical ? false : physicsEnabled;
      networkRef.current.setOptions(getNetworkOptions(newMode, nextPhysics));
      setTimeout(() => {
        networkRef.current?.fit({
          animation: { duration: 600, easingFunction: 'easeInOutQuad' },
        });
      }, 100);
    }
  };

  /**
   * Canh giữa toàn bộ đồ thị
   */
  const handleFit = () => {
    if (networkRef.current) {
      networkRef.current.fit({
        animation: { duration: 600, easingFunction: 'easeInOutQuad' },
      });
    }
  };

  /**
   * Phóng to
   */
  const handleZoomIn = () => {
    if (networkRef.current) {
      const scale = networkRef.current.getScale();
      networkRef.current.moveTo({
        scale: scale * 1.3,
        animation: { duration: 300, easingFunction: 'easeInOutQuad' },
      });
    }
  };

  /**
   * Thu nhỏ
   */
  const handleZoomOut = () => {
    if (networkRef.current) {
      const scale = networkRef.current.getScale();
      networkRef.current.moveTo({
        scale: scale * 0.7,
        animation: { duration: 300, easingFunction: 'easeInOutQuad' },
      });
    }
  };

  /**
   * Tìm kiếm nhanh issue trên đồ thị
   */
  const handleSearchSubmit = (e) => {
    e.preventDefault();
    const query = searchQuery.trim().toUpperCase();
    if (!query) return;

    // Tìm kiếm chính xác key hoặc bắt đầu bằng
    let target = nodeMap.get(query);
    if (!target) {
      target = Array.from(nodeMap.values()).find(
        (n) => n.key.toUpperCase().includes(query) || (n.summary && n.summary.toUpperCase().includes(query))
      );
    }

    if (target && networkRef.current) {
      if (onSelectIssue) onSelectIssue(target.id);
      networkRef.current.focus(target.id, {
        scale: 1.4,
        animation: { duration: 800, easingFunction: 'easeInOutQuad' },
      });
    }
  };

  return (
    <Card withBorder radius="md" padding="md" shadow="sm" style={{ position: 'relative', minHeight: 650 }}>
      <Stack gap="sm">
        {/* Thanh công cụ tiêu đề & Thông số tổng quan */}
        <Group justify="space-between" align="center" wrap="wrap">
          <Group gap="xs">
            <ThemeIcon size="lg" radius="md" color="indigo" variant="light">
              <IconTopologyStarRing3 size={22} stroke={1.5} />
            </ThemeIcon>
            <Box>
              <Group gap="xs">
                <Text fw={700} size="md">
                  Đồ thị Mạng lưới Phụ thuộc & Điểm nghẽn Dự án
                </Text>
                <Badge size="sm" variant="filled" color="indigo">
                  {summary.total_nodes} Tasks
                </Badge>
                <Badge size="sm" variant="light" color="gray">
                  {summary.total_edges} Dependencies
                </Badge>
              </Group>
              <Text size="xs" c="dimmed">
                Trực quan hóa luồng công việc thời gian thực, phát hiện sớm nguy cơ trễ hạn và các nút thắt cổ chai
              </Text>
            </Box>
          </Group>

          {/* Nhóm nút thu phóng & điều khiển camera */}
          <Group gap={6}>
            <Tooltip label="Canh giữa toàn màn hình" withArrow position="bottom">
              <ActionIcon variant="default" size="md" onClick={handleFit} aria-label="Fit view">
                <IconFocusCentered size={17} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Phóng to" withArrow position="bottom">
              <ActionIcon variant="default" size="md" onClick={handleZoomIn} aria-label="Zoom in">
                <IconZoomIn size={17} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Thu nhỏ" withArrow position="bottom">
              <ActionIcon variant="default" size="md" onClick={handleZoomOut} aria-label="Zoom out">
                <IconZoomOut size={17} />
              </ActionIcon>
            </Tooltip>
            <Tooltip label={physicsEnabled ? 'Tạm dừng mô phỏng lực' : 'Kích hoạt mô phỏng lực'} withArrow position="bottom">
              <ActionIcon
                variant={physicsEnabled ? 'light' : 'default'}
                color={physicsEnabled ? 'blue' : 'gray'}
                size="md"
                onClick={handleTogglePhysics}
                aria-label="Toggle physics"
              >
                {physicsEnabled ? <IconPlayerPause size={17} /> : <IconPlayerPlay size={17} />}
              </ActionIcon>
            </Tooltip>
            <Tooltip label="Làm mới dữ liệu đồ thị" withArrow position="bottom">
              <ActionIcon
                variant="default"
                size="md"
                loading={isFetching}
                onClick={() => refetch()}
                aria-label="Refresh graph"
              >
                <IconRefresh size={17} />
              </ActionIcon>
            </Tooltip>
          </Group>
        </Group>

        {/* Thanh thẻ số liệu cảnh báo (Mini KPI Bar) */}
        <Group gap="xs" wrap="wrap">
          <Badge
            size="md"
            variant={activeFilter === 'BOTTLENECK' ? 'filled' : 'light'}
            color="red"
            leftSection={<IconAlertTriangle size={14} />}
            style={{ cursor: 'pointer' }}
            onClick={() => setActiveFilter((prev) => (prev === 'BOTTLENECK' ? 'ALL' : 'BOTTLENECK'))}
          >
            {summary.bottlenecks_count} Điểm nghẽn nghiêm trọng
          </Badge>

          <Badge
            size="md"
            variant={activeFilter === 'OVERDUE' ? 'filled' : 'light'}
            color="red"
            leftSection={<IconClock size={14} />}
            style={{ cursor: 'pointer' }}
            onClick={() => setActiveFilter((prev) => (prev === 'OVERDUE' ? 'ALL' : 'OVERDUE'))}
          >
            {summary.overdue_count} Task trễ hạn
          </Badge>

          <Badge
            size="md"
            variant={activeFilter === 'BLOCKED' ? 'filled' : 'light'}
            color="orange"
            leftSection={<IconLock size={14} />}
            style={{ cursor: 'pointer' }}
            onClick={() => setActiveFilter((prev) => (prev === 'BLOCKED' ? 'ALL' : 'BLOCKED'))}
          >
            {summary.blocked_count} Đang bị chặn
          </Badge>

          <Badge
            size="md"
            variant={activeFilter === 'HIGH_RISK' ? 'filled' : 'light'}
            color="orange"
            leftSection={<IconFlame size={14} />}
            style={{ cursor: 'pointer' }}
            onClick={() => setActiveFilter((prev) => (prev === 'HIGH_RISK' ? 'ALL' : 'HIGH_RISK'))}
          >
            {summary.high_risk_count} Nguy cơ cao
          </Badge>

          <Badge
            size="md"
            variant={activeFilter === 'CRITICAL' ? 'filled' : 'light'}
            color="violet"
            leftSection={<IconRoute size={14} />}
            style={{ cursor: 'pointer' }}
            onClick={() => setActiveFilter((prev) => (prev === 'CRITICAL' ? 'ALL' : 'CRITICAL'))}
          >
            {summary.critical_count} Trọng yếu TGN
          </Badge>

          <Badge
            size="md"
            variant="light"
            color="green"
            leftSection={<IconCheck size={14} />}
          >
            {summary.done_count} Đã hoàn thành
          </Badge>
        </Group>

        {/* Thanh điều khiển bộ lọc & bố cục */}
        <Group justify="space-between" align="center" wrap="wrap" gap="xs">
          {/* Bộ lọc điểm cần quan tâm */}
          <Group gap={6} wrap="wrap">
            <Text size="xs" fw={600} c="dimmed">
              Bộ lọc:
            </Text>
            <SegmentedControl
              size="xs"
              value={activeFilter}
              onChange={setActiveFilter}
              data={[
                { label: 'Tất cả', value: 'ALL' },
                { label: '🚨 Điểm nghẽn', value: 'BOTTLENECK' },
                { label: '⏰ Trễ hạn', value: 'OVERDUE' },
                { label: '⛓️ Bị chặn', value: 'BLOCKED' },
                { label: '🔥 Nguy cơ cao', value: 'HIGH_RISK' },
                { label: '🎯 Đường găng TGN', value: 'CRITICAL' },
              ]}
            />
          </Group>

          {/* Chế độ hiển thị bố cục & Tìm kiếm */}
          <Group gap="xs" wrap="wrap">
            <SegmentedControl
              size="xs"
              value={layoutMode}
              onChange={handleChangeLayout}
              data={[
                { label: 'Lực liên kết (Force)', value: 'physics' },
                { label: 'Phân cấp (Trái sang Phải)', value: 'hierarchical_lr' },
                { label: 'Phân cấp (Trên xuống Dưới)', value: 'hierarchical_ud' },
              ]}
            />

            <form onSubmit={handleSearchSubmit} style={{ width: 170 }}>
              <TextInput
                size="xs"
                placeholder="Tìm mã task (VD: 102)"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                rightSection={
                  <ActionIcon size="xs" variant="subtle" type="submit">
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

        {/* Chú giải có thể đóng/mở */}
        <Collapse in={isLegendOpen}>
          <Paper withBorder p="xs" radius="sm" bg="var(--mantine-color-gray-0)">
            <Group justify="space-between" gap="md" wrap="wrap">
              <Group gap="xs">
                <Text size="xs" fw={700}>Mã màu Node:</Text>
                <Badge size="xs" color="red" variant="filled">🔴 Điểm nghẽn / Quá hạn</Badge>
                <Badge size="xs" color="violet" variant="filled">🟣 Trọng yếu TGN</Badge>
                <Badge size="xs" color="orange" variant="filled">🟠 Bị chặn / Nguy cơ cao</Badge>
                <Badge size="xs" color="yellow" variant="filled">🟡 Nguy cơ TB</Badge>
                <Badge size="xs" color="blue" variant="filled">🔵 Bình thường</Badge>
                <Badge size="xs" color="green" variant="filled">🟢 Đã xong</Badge>
              </Group>

              <Group gap="xs">
                <Text size="xs" fw={700}>Đường liên kết (Edges):</Text>
                <Text size="xs">➡️ <b>Mũi tên chỉ chiều:</b> Task Tiên quyết (Blocker) ➔ Task Bị chặn (Dependent)</Text>
                <Text size="xs" c="red">━━ Đỏ: Chặn nghẽn</Text>
                <Text size="xs" c="grape">┅┅ Tím đứt nét: Đường găng TGN</Text>
              </Group>
            </Group>
          </Paper>
        </Collapse>

        {/* Khung vẽ Canvas đồ thị mạng lưới */}
        <Box
          style={{
            position: 'relative',
            height: 540,
            borderRadius: 8,
            border: '1px solid var(--mantine-color-gray-3)',
            backgroundColor: '#fafbfc',
            overflow: 'hidden',
          }}
        >
          {isLoading && (
            <Center h="100%">
              <Stack align="center" gap="xs">
                <Loader size="md" type="dots" />
                <Text size="sm" c="dimmed">Đang tính toán cấu trúc mạng lưới và điểm nghẽn...</Text>
              </Stack>
            </Center>
          )}

          {isError && (
            <Center h="100%">
              <Alert icon={<IconAlertTriangle size={18} />} color="red" title="Lỗi tải đồ thị">
                Không thể tải dữ liệu mạng lưới của dự án. Vui lòng thử lại.
              </Alert>
            </Center>
          )}

          {!isLoading && !isError && graphData?.nodes?.length === 0 && (
            <Center h="100%">
              <Stack align="center" gap="xs">
                <ThemeIcon size="xl" radius="xl" color="gray" variant="light">
                  <IconArrowsSplit size={26} />
                </ThemeIcon>
                <Text fw={600} size="sm">Chưa có liên kết phụ thuộc nào</Text>
                <Text size="xs" c="dimmed">
                  Dự án hiện tại chưa có các issue liên kết hoặc bị chặn để vẽ đồ thị.
                </Text>
              </Stack>
            </Center>
          )}

          {/* Vùng gắn Vis Network Canvas */}
          <div
            ref={containerRef}
            style={{
              width: '100%',
              height: '100%',
              display: isLoading || isError ? 'none' : 'block',
              cursor: 'grab',
            }}
          />

          {/* Hộp chỉ dẫn nhanh ở góc dưới bên trái */}
          <Box
            style={{
              position: 'absolute',
              bottom: 10,
              left: 12,
              pointerEvents: 'none',
              backgroundColor: 'rgba(255, 255, 255, 0.88)',
              backdropFilter: 'blur(4px)',
              padding: '4px 10px',
              borderRadius: 6,
              border: '1px solid #e9ecef',
            }}
          >
            <Text size="xs" c="dimmed">
              💡 <b>Mẹo:</b> Click node để làm nổi bật chuỗi phụ thuộc & mở panel chi tiết | Click khoảng trắng để reset
            </Text>
          </Box>

          {/* Rich Floating Tooltip khi hover trên node */}
          {hoveredNodeData && (
            <Paper
              shadow="md"
              withBorder
              p="sm"
              radius="md"
              style={{
                position: 'absolute',
                top: Math.max(10, Math.min(tooltipPos.y - 120, 360)),
                left: Math.max(10, Math.min(tooltipPos.x + 20, 680)),
                zIndex: 100,
                width: 320,
                backgroundColor: 'rgba(255, 255, 255, 0.98)',
                backdropFilter: 'blur(6px)',
                pointerEvents: 'none',
                boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
              }}
            >
              <Stack gap="xs">
                <Group justify="space-between" align="center" wrap="nowrap">
                  <Group gap={6}>
                    <Text fw={700} size="sm">
                      {hoveredNodeData.key}
                    </Text>
                    <Badge size="xs" variant="outline" color="blue">
                      {hoveredNodeData.issuetype || 'Task'}
                    </Badge>
                  </Group>

                  <Badge
                    size="xs"
                    color={
                      hoveredNodeData.status_category === 'done'
                        ? 'green'
                        : hoveredNodeData.blocked
                        ? 'orange'
                        : hoveredNodeData.status_category === 'indeterminate'
                        ? 'blue'
                        : 'gray'
                    }
                  >
                    {hoveredNodeData.status || 'Chưa cập nhật'}
                  </Badge>
                </Group>

                <Text size="xs" lineClamp={2} fw={500}>
                  {hoveredNodeData.summary}
                </Text>

                <Divider size="xs" />

                {/* Hạn chót & Điểm nghẽn */}
                <Group justify="space-between" gap="xs">
                  <Text size="xs" c="dimmed">Người phụ trách:</Text>
                  <Text size="xs" fw={500}>{hoveredNodeData.assignee_name || 'Chưa phân công'}</Text>
                </Group>

                <Group justify="space-between" gap="xs">
                  <Text size="xs" c="dimmed">Hạn chót:</Text>
                  {hoveredNodeData.is_overdue ? (
                    <Badge size="xs" color="red" variant="filled">
                      Quá hạn {hoveredNodeData.overdue_days} ngày!
                    </Badge>
                  ) : hoveredNodeData.duedate ? (
                    <Text size="xs" fw={500}>{hoveredNodeData.duedate}</Text>
                  ) : (
                    <Text size="xs" c="dimmed">Chưa đặt</Text>
                  )}
                </Group>

                {/* Chỉ số rủi ro AI / ML */}
                <Box>
                  <Group justify="space-between" mb={2}>
                    <Text size="xs" c="dimmed">Xác suất trễ hạn (P_delay):</Text>
                    <Text size="xs" fw={700} c={hoveredNodeData.delay_value >= 0.5 ? 'red' : 'blue'}>
                      {Math.round((hoveredNodeData.delay_value || 0) * 100)}%
                    </Text>
                  </Group>
                  <Progress
                    value={(hoveredNodeData.delay_value || 0) * 100}
                    size="xs"
                    color={hoveredNodeData.delay_value >= 0.5 ? 'red' : 'blue'}
                    radius="xl"
                  />
                </Box>

                {hoveredNodeData.crit_score > 0 && (
                  <Group justify="space-between" gap="xs">
                    <Text size="xs" c="dimmed">Trọng yếu TGN Memory:</Text>
                    <Badge size="xs" color={hoveredNodeData.is_critical ? 'grape' : 'gray'}>
                      {hoveredNodeData.crit_score.toFixed(2)} {hoveredNodeData.is_critical ? '(Top 5%)' : ''}
                    </Badge>
                  </Group>
                )}

                {/* Cảnh báo Điểm nghẽn nếu có */}
                {hoveredNodeData.is_bottleneck && (
                  <Alert
                    p="xs"
                    color="red"
                    variant="light"
                    icon={<IconAlertTriangle size={15} />}
                    title="Nút thắt cổ chai (Bottleneck)"
                  >
                    <Text size="xs">
                      Đang chặn <b>{hoveredNodeData.blocks_count}</b> task khác: {hoveredNodeData.blocks_keys.join(', ')}
                    </Text>
                  </Alert>
                )}

                {hoveredNodeData.blocked && (
                  <Text size="xs" c="orange">
                    ⛓️ Bị chặn bởi: <b>{hoveredNodeData.blocked_by_keys.join(', ')}</b>
                  </Text>
                )}
              </Stack>
            </Paper>
          )}
        </Box>
      </Stack>
    </Card>
  );
}
