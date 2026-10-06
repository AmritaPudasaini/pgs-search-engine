import { cookies } from "next/headers";
import type { User } from "@/lib/types";

export const SESSION_COOKIE = "pgs_session";

export const MOCK_USERS: Array<User & { password: string }> = [
  {
    email: "admin@pgs.local",
    password: "admin123",
    name: "Admin",
    role: "admin",
  },
  {
    email: "analyst@pgs.local",
    password: "analyst123",
    name: "Search Analyst",
    role: "analyst",
  },
];

export function encodeSession(user: User): string {
  return Buffer.from(JSON.stringify(user), "utf8").toString("base64url");
}

export function decodeSession(value: string): User | null {
  try {
    const parsed = JSON.parse(Buffer.from(value, "base64url").toString("utf8"));
    if (parsed && typeof parsed.email === "string") return parsed as User;
    return null;
  } catch {
    return null;
  }
}

export async function getSessionUser(): Promise<User | null> {
  const store = await cookies();
  const raw = store.get(SESSION_COOKIE)?.value;
  if (!raw) return null;
  return decodeSession(raw);
}
