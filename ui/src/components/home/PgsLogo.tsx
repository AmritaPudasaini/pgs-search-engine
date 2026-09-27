import { cn } from "@/lib/cn";

const LETTER_COLORS = [
  "text-blue-500",
  "text-rose-500",
  "text-amber-500",
  "text-blue-500",
  "text-emerald-500",
  "text-rose-500",
];

export function PgsLogo({ size = "large" }: { size?: "large" | "small" }) {
  const text = "PGS Search";
  return (
    <div
      className={cn(
        "select-none font-semibold tracking-tight",
        size === "large" ? "text-6xl sm:text-7xl" : "text-2xl"
      )}
    >
      {text.split("").map((char, i) => (
        <span key={i} className={char === " " ? "" : LETTER_COLORS[i % LETTER_COLORS.length]}>
          {char}
        </span>
      ))}
    </div>
  );
}
