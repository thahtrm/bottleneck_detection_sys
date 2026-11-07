import React, { useState } from 'react';
import {
  Container,
  Paper,
  Title,
  Text,
  TextInput,
  PasswordInput,
  Button,
  Alert,
  Stack,
  ThemeIcon,
  Center,
  Box,
} from '@mantine/core';
import { IconMail, IconLock, IconAlertCircle, IconShieldLock } from '@tabler/icons-react';
import { useAuth } from '../context/AuthContext';

export default function Login() {
  const { login } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  const handleSubmit = async (e) => {
    e?.preventDefault();
    const cleanEmail = email.trim();

    if (!cleanEmail) {
      setErrorMessage('Vui lòng nhập địa chỉ email.');
      return;
    }

    if (!password) {
      setErrorMessage('Vui lòng nhập mật khẩu.');
      return;
    }

    setSubmitting(true);
    setErrorMessage(null);

    try {
      await login(cleanEmail, password);
    } catch (err) {
      setErrorMessage(err.message || 'Email hoặc mật khẩu không chính xác.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Center style={{ minHeight: '100vh' }} py="xl" bg="gray.0">
      <Container size={420} my={40} style={{ width: '100%' }}>
        <Stack align="center" mb="lg" gap="xs">
          <ThemeIcon size={56} radius="xl" color="blue" variant="light">
            <IconShieldLock size={32} />
          </ThemeIcon>
          <Title order={2} ta="center" fw={700}>
            Early Risk Web
          </Title>
          <Text c="dimmed" size="sm" ta="center">
            Hệ thống phát hiện &amp; cảnh báo sớm rủi ro tiến độ dự án Jira
          </Text>
        </Stack>

        <Paper withBorder shadow="md" p={30} radius="md">
          <form onSubmit={handleSubmit}>
            <Stack gap="md">
              {errorMessage && (
                <Alert
                  icon={<IconAlertCircle size={16} />}
                  title="Đăng nhập không thành công"
                  color="red"
                  radius="md"
                  withCloseButton
                  onClose={() => setErrorMessage(null)}
                >
                  {errorMessage}
                </Alert>
              )}

              <TextInput
                label="Địa chỉ Email"
                placeholder="admin@earlyrisk.local"
                required
                leftSection={<IconMail size={16} />}
                value={email}
                onChange={(event) => setEmail(event.currentTarget.value)}
                autoComplete="email"
                autoFocus
              />

              <PasswordInput
                label="Mật khẩu"
                placeholder="Nhập mật khẩu"
                required
                leftSection={<IconLock size={16} />}
                value={password}
                onChange={(event) => setPassword(event.currentTarget.value)}
                autoComplete="current-password"
              />

              <Button
                type="submit"
                fullWidth
                loading={submitting}
                mt="sm"
                color="blue"
              >
                Đăng nhập
              </Button>
            </Stack>
          </form>

          <Box mt="lg" pt="sm" style={{ borderTop: '1px solid var(--mantine-color-gray-2)' }}>
            <Text size="xs" c="dimmed" ta="center">
              Tài khoản mẫu: <b>admin@earlyrisk.local</b> | <b>Admin@123456</b>
            </Text>
          </Box>
        </Paper>
      </Container>
    </Center>
  );
}
