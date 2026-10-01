import Link from "next/link";
import { Suspense } from "react";
import { PgsLogo } from "@/components/home/PgsLogo";
import { LoginForm } from "@/components/auth/LoginForm";

export default function LoginPage() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-8 bg-white px-6 dark:bg-slate-950">
      <Link href="/">
        <PgsLogo size="small" />
      </Link>
      <div className="w-full max-w-sm rounded-2xl border border-slate-200 p-6 shadow-sm dark:border-slate-800">
        <h1 className="mb-1 text-lg font-semibold text-slate-900 dark:text-slate-100">Sign in</h1>
        <p className="mb-6 text-sm text-slate-500 dark:text-slate-400">
          Access the PGS Search dashboard and geo tagging tools.
        </p>
        <Suspense>
          <LoginForm />
        </Suspense>
      </div>
    </div>
  );
}
