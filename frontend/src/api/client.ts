import axios from 'axios';
import { getAuth } from 'firebase/auth';

const client = axios.create({ baseURL: '' });
const DEV_LOGIN_STORAGE_KEY = 'fantasy_cricket_dev_login';

export function isDevLoginEnabled() {
  try {
    return localStorage.getItem(DEV_LOGIN_STORAGE_KEY) === '1';
  } catch {
    return false;
  }
}

client.interceptors.request.use(async (config) => {
  try {
    const auth = getAuth();
    const user = auth.currentUser;
    if (user) {
      const token = await user.getIdToken();
      config.headers.Authorization = `Bearer ${token}`;
    } else if (isDevLoginEnabled()) {
      config.headers['X-Dev-Login'] = '1';
    }
  } catch {
    if (isDevLoginEnabled()) {
      config.headers['X-Dev-Login'] = '1';
    }
  }
  return config;
});

export default client;
