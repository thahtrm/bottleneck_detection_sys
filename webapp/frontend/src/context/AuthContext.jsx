import React, { createContext, useContext, useState, useEffect } from 'react';
import { notifications } from '@mantine/notifications';
import { IconCheck, IconLogout } from '@tabler/icons-react';
import { login as loginApi, logout as logoutApi, getMe as getMeApi } from '../api/client';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    let isMounted = true;

    async function initAuth() {
      try {
        const userData = await getMeApi();
        if (isMounted) {
          setUser(userData);
          setError(null);
        }
      } catch (err) {
        if (isMounted) {
          setUser(null);
          // If 401, this is expected when not logged in
          if (err.status !== 401) {
            setError(err.message || 'Không thể xác thực người dùng');
          }
        }
      } finally {
        if (isMounted) {
          setLoading(false);
        }
      }
    }

    initAuth();

    return () => {
      isMounted = false;
    };
  }, []);

  const loginUser = async (email, password) => {
    setError(null);
    try {
      const userData = await loginApi(email, password);
      setUser(userData);
      notifications.show({
        title: 'Đăng nhập thành công',
        message: `Chào mừng ${userData.name || userData.email}!`,
        color: 'teal',
        icon: <IconCheck size={18} />,
      });
      return userData;
    } catch (err) {
      setError(err.message || 'Đăng nhập thất bại');
      throw err;
    }
  };

  const logoutUser = async () => {
    try {
      await logoutApi();
    } catch (err) {
      console.error('Lỗi khi đăng xuất:', err);
    } finally {
      setUser(null);
      setError(null);
      notifications.show({
        title: 'Đã đăng xuất',
        message: 'Bạn đã đăng xuất khỏi hệ thống thành công.',
        color: 'blue',
        icon: <IconLogout size={18} />,
      });
    }
  };

  const value = {
    user,
    loading,
    error,
    login: loginUser,
    logout: logoutUser,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth phải được sử dụng bên trong AuthProvider');
  }
  return context;
}
