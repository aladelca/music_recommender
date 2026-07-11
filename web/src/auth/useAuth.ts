import { createContext, useContext } from "react";

import type { ProductUser } from "../api/schemas";

export type AuthContextValue = {
  user: ProductUser | null;
  loading: boolean;
  error: Error | null;
  refresh: () => Promise<void>;
  logout: () => Promise<void>;
};

export const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
