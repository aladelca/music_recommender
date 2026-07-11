import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { PropsWithChildren } from "react";

import { api, ApiError } from "../api/client";
import { AuthContext } from "./useAuth";

export function AuthProvider({ children }: PropsWithChildren) {
  const queryClient = useQueryClient();
  const query = useQuery({
    queryKey: ["auth", "me"],
    queryFn: api.me,
    retry: false,
  });
  const logoutMutation = useMutation({
    mutationFn: api.logout,
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["auth"] });
    },
  });
  const anonymous = query.error instanceof ApiError && query.error.status === 401;

  return (
    <AuthContext.Provider
      value={{
        user: anonymous ? null : (query.data ?? null),
        loading: query.isLoading,
        error: !anonymous && query.error instanceof Error ? query.error : null,
        refresh: async () => {
          await query.refetch();
        },
        logout: async () => {
          await logoutMutation.mutateAsync();
        },
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}
