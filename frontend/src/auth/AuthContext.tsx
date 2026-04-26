import { createContext, useContext, useState, useEffect, useRef, type ReactNode } from 'react';
import axios from 'axios';
import type { User as FirebaseUser } from 'firebase/auth';
import {
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut,
  onAuthStateChanged,
} from 'firebase/auth';
import { auth } from './firebase';
import client, { isDevLoginEnabled } from '../api/client';
import type { User } from '../types';

interface AuthContextType {
  firebaseUser: FirebaseUser | null;
  profile: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, name: string) => Promise<void>;
  logout: () => Promise<void>;
  devLogin: () => Promise<void>;
  refreshProfile: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

const PROFILE_RETRY_INTERVAL_MS = 2_000;

type ProfileFetchResult = {
  profile: User | null;
  backendReady: boolean;
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [firebaseUser, setFirebaseUser] = useState<FirebaseUser | null>(null);
  const [profile, setProfile] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const profileRetryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Fetch profile from backend
  const fetchProfile = async (
    devLogin = false,
    firebaseUserOverride: FirebaseUser | null = null
  ): Promise<ProfileFetchResult> => {
    try {
      if (devLogin || (!firebaseUserOverride && isDevLoginEnabled())) {
        const res = await client.get('/api/auth/dev-login');
        setProfile(res.data);
        return { profile: res.data, backendReady: true };
      }

      if (firebaseUserOverride) {
        const token = await firebaseUserOverride.getIdToken();
        const res = await client.get('/api/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        });
        setProfile(res.data);
        return { profile: res.data, backendReady: true };
      }

      const res = await client.get('/api/auth/me');
      setProfile(res.data);
      return { profile: res.data, backendReady: true };
    } catch (error) {
      setProfile(null);
      const backendReady = !(axios.isAxiosError(error) && !error.response);
      return { profile: null, backendReady };
    }
  };

  const clearProfileRetryTimer = () => {
    if (profileRetryTimerRef.current) {
      clearTimeout(profileRetryTimerRef.current);
      profileRetryTimerRef.current = null;
    }
  };

  const retryFirebaseProfile = async (user: FirebaseUser) => {
    clearProfileRetryTimer();
    const result = await fetchProfile(false, user);
    if (result.profile) {
      setLoading(false);
      return;
    }

    if (!result.backendReady) {
      profileRetryTimerRef.current = setTimeout(() => {
        void retryFirebaseProfile(user);
      }, PROFILE_RETRY_INTERVAL_MS);
      return;
    }

    setProfile(null);
    setLoading(false);
    await signOut(auth);
  };

  useEffect(() => {
    const unsub = onAuthStateChanged(auth, async (user) => {
      setFirebaseUser(user);
      if (user) {
        setLoading(true);
        await retryFirebaseProfile(user);
      } else {
        clearProfileRetryTimer();
        setProfile(null);
        setLoading(false);
      }
    });
    return () => {
      clearProfileRetryTimer();
      unsub();
    };
  }, []);

  const login = async (email: string, password: string) => {
    const cred = await signInWithEmailAndPassword(auth, email, password);
    const result = await fetchProfile(false, cred.user);
    if (!result.profile) {
      await signOut(auth);
      if (!result.backendReady) {
        throw new Error('The app is still starting up. Please try again in a moment.');
      }
      throw new Error('Your account is not registered in the app yet.');
    }
  };

  const register = async (email: string, password: string, name: string) => {
    const cred = await createUserWithEmailAndPassword(auth, email, password);
    // Register in backend
    const token = await cred.user.getIdToken();
    await client.post(
      '/api/auth/register',
      { name },
      { headers: { Authorization: `Bearer ${token}` } }
    );
    const result = await fetchProfile(false, cred.user);
    if (!result.profile) {
      await signOut(auth);
      if (!result.backendReady) {
        throw new Error('The app is still starting up. Please try again in a moment.');
      }
      throw new Error('Registration completed, but the profile could not be loaded.');
    }
  };

  const logout = async () => {
    await signOut(auth);
    setProfile(null);
    try {
      localStorage.removeItem('fantasy_cricket_dev_login');
    } catch {
      // Ignore storage failures.
    }
  };

  // Dev mode login - works without Firebase
  const devLogin = async () => {
    try {
      localStorage.setItem('fantasy_cricket_dev_login', '1');
    } catch {
      // Ignore storage failures.
    }
    const result = await fetchProfile(true);
    if (!result.profile) {
      try {
        localStorage.removeItem('fantasy_cricket_dev_login');
      } catch {
        // Ignore storage failures.
      }
      throw new Error('Dev login failed.');
    }
    setLoading(false);
  };

  return (
    <AuthContext.Provider
      value={{
        firebaseUser,
        profile,
        loading,
        login,
        register,
        logout,
        devLogin,
        refreshProfile: async () => {
          await fetchProfile();
        },
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error('useAuth must be inside AuthProvider');
  return ctx;
}
