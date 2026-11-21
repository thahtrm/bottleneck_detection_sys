import React, { useState } from 'react';
import { ActionIcon, Button, Group, Stack, Text, TextInput } from '@mantine/core';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { IconX } from '@tabler/icons-react';
import { getChatSchedule, getChatSystemStatus, putChatSchedule } from '../../api/client';

const HHMM = /^([01]\d|2[0-3]):[0-5]\d$/;

/** User-scoped report schedule (max 3 HH:MM) — migrated from sticky PmChat. */
export default function ReportScheduleSection({ onViewReports }) {
  const queryClient = useQueryClient();
  const [clock, setClock] = useState('');
  const schedule = useQuery({
    queryKey: ['chat-schedule'],
    queryFn: getChatSchedule,
  });
  const systemStatus = useQuery({
    queryKey: ['chat-system-status'],
    queryFn: getChatSystemStatus,
    staleTime: 60000,
  });
  const saveSchedule = useMutation({
    mutationFn: putChatSchedule,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['chat-schedule'] }),
  });

  const times = schedule.data?.times ?? [];
  const tz = systemStatus.data?.tz;

  const addTime = () => {
    const value = clock.trim();
    if (!HHMM.test(value) || times.includes(value) || times.length >= 3) return;
    setClock('');
    saveSchedule.mutate([...times, value]);
  };

  return (
    <Stack gap="sm">
      <Text className="erw-settings-body">
        Lịch weekday theo giờ máy chủ{tz ? ` (${tz})` : ''} sinh Báo cáo sức khỏe dự án (7 mục, md+PDF) cho
        mọi dự án bạn là PM (không theo từng project).
      </Text>
      <Group gap={6}>
        {times.map((time) => (
          <Group key={time} gap={2} className="erw-settings-chip">
            <Text className="erw-settings-body">{time}</Text>
            <ActionIcon
              variant="subtle"
              size="sm"
              className="erw-settings-link"
              aria-label={`Xóa ${time}`}
              onClick={() => saveSchedule.mutate(times.filter((item) => item !== time))}
            >
              <IconX size={12} />
            </ActionIcon>
          </Group>
        ))}
        {times.length === 0 && !schedule.isLoading && (
          <Text className="erw-settings-meta">Chưa đặt giờ báo cáo.</Text>
        )}
      </Group>
      <Group gap="xs">
        <TextInput
          className="erw-settings-input"
          placeholder="HH:MM"
          value={clock}
          onChange={(event) => setClock(event.currentTarget.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter') addTime();
          }}
          w={100}
          size="sm"
          aria-label="Giờ báo cáo"
        />
        <Button
          className="erw-settings-btn-secondary"
          onClick={addTime}
          disabled={times.length >= 3}
          loading={saveSchedule.isPending}
        >
          Thêm giờ
        </Button>
        {onViewReports && (
          <Button className="erw-settings-btn-secondary" onClick={onViewReports}>
            Xem báo cáo đã tạo
          </Button>
        )}
      </Group>
      {schedule.isError && (
        <Text className="erw-settings-error">{schedule.error?.message || 'Không tải được lịch.'}</Text>
      )}
      {saveSchedule.isError && (
        <Text className="erw-settings-error">{saveSchedule.error?.message || 'Không lưu được giờ báo cáo.'}</Text>
      )}
    </Stack>
  );
}
