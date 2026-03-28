import { create } from 'zustand';

const getBaseUrl = () => {
  if (import.meta.env.VITE_BACKEND_URL) {
    return import.meta.env.VITE_BACKEND_URL;
  }
  if (import.meta.env.PROD) {
    return window.location.origin;
  }
  return 'http://localhost:8000';
};

export const useConfigStore = create((set, get) => ({
  apiBaseUrl: getBaseUrl(),

  getApiUrl: (path = '') => {
    const baseUrl = get().apiBaseUrl;
    const cleanPath = path.startsWith('/') ? path : `/${path}`;
    return `${baseUrl}${cleanPath}`;
  },
}));

export const apiUrl = (path) => useConfigStore.getState().getApiUrl(path);
