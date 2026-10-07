import { NextResponse } from "next/server";
import { MOCK_USERS, SESSION_COOKIE, encodeSession } from "@/lib/auth/session";
import type { User } from "@/lib/types";

export async function POST(request: Request) {
  const body = await request.json().catch(() => null);
  const email = typeof body?.email === "string" ? body.email.trim().toLowerCase() : "";
  const password = typeof body?.password === "string" ? body.password : "";

  const match = MOCK_USERS.find(
    (u) => u.email.toLowerCase() === email && u.password === password
  );

  if (!match) {
    return NextResponse.json(
      { error: "Invalid email or password." },
      { status: 401 }
    );
  }

  const user: User = { email: match.email, name: match.name, role: match.role };
  const response = NextResponse.json({ user });
  response.cookies.set(SESSION_COOKIE, encodeSession(user), {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: 60 * 60 * 8,
  });
  return response;
}
