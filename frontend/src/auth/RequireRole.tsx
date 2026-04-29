import type { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { useAuth } from "@/auth/useAuth";

interface Props {
  roles: string[];
  children: ReactNode;
}

export function RequireRole({ roles, children }: Props) {
  const { initialized, roles: userRoles } = useAuth();
  if (!initialized) return null;
  if (!userRoles.some((r) => roles.includes(r))) {
    return <Navigate to="/unauthorized" replace />;
  }
  return <>{children}</>;
}

export function hasAnyRole(userRoles: string[], required: string[]): boolean {
  return userRoles.some((r) => required.includes(r));
}
