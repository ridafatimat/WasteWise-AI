import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";

import {
  getMe,
  login as apiLogin,
} from "@/services/api";
import {
  TOKEN_KEY,
} from "@/services/api/client";
import type {
  AuthUser,
} from "@/types";

interface AuthCtx {
  user: AuthUser | null;
  token: string | null;
  isLoading: boolean;
  isAuthenticated: boolean;
  login: (
    email: string,
    password: string,
  ) => Promise<void>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const Ctx =
  createContext<AuthCtx | null>(
    null,
  );

export function AuthProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [user, setUser] =
    useState<AuthUser | null>(
      null,
    );

  const [token, setToken] =
    useState<string | null>(
      null,
    );

  const [
    isLoading,
    setIsLoading,
  ] = useState(true);

  const refresh = async () => {
    try {
      const me =
        await getMe();

      setUser(me);
    } catch {
      setUser(null);
      setToken(null);

      if (
        typeof window !==
        "undefined"
      ) {
        localStorage.removeItem(
          TOKEN_KEY,
        );
      }
    }
  };

  useEffect(() => {
    const storedToken =
      typeof window !==
      "undefined"
        ? localStorage.getItem(
            TOKEN_KEY,
          )
        : null;

    setToken(storedToken);

    if (storedToken) {
      refresh().finally(() =>
        setIsLoading(false),
      );
    } else {
      setIsLoading(false);
    }
  }, []);

  const login = async (
    email: string,
    password: string,
  ) => {
    const response =
      await apiLogin(
        email,
        password,
      );

    const accessToken =
      response.access_token ||
      response.token;

    if (!accessToken) {
      throw new Error(
        "No token returned from server.",
      );
    }

    localStorage.setItem(
      TOKEN_KEY,
      accessToken,
    );

    setToken(accessToken);

    if (response.user) {
      setUser(response.user);
    } else {
      await refresh();
    }
  };

  const logout = () => {
    localStorage.removeItem(
      TOKEN_KEY,
    );

    setToken(null);
    setUser(null);
  };

  return (
    <Ctx.Provider
      value={{
        user,
        token,
        isLoading,
        isAuthenticated:
          Boolean(token),
        login,
        logout,
        refresh,
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const context =
    useContext(Ctx);

  if (!context) {
    throw new Error(
      "useAuth must be used within AuthProvider",
    );
  }

  return context;
}