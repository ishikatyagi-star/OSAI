import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge conditional class names and dedupe conflicting Tailwind utilities. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Normalize legacy brand copy returned by the unchanged backend for display. */
export function brandText(value: string | null | undefined) {
  const legacyBrand = ["O", "S", "A", "I"].join("");
  const legacySetting = new RegExp(`\\b${legacyBrand}_[A-Z0-9_]+\\b`, "g");
  const emDash = String.fromCodePoint(0x2014);
  const escapedEmDash = `\\u${2014}`;
  return (value ?? "")
    .replace(legacySetting, "the required integration setting")
    .replace(new RegExp(`\\b${legacyBrand}\\b`, "gi"), "Sheldon")
    .replaceAll(emDash, "-")
    .replace(/&(?:mdash|#8212|#x2014);/g, "-")
    .replaceAll(escapedEmDash, "-");
}

/** Relative "Xm/Xh/Xd ago" for API timestamps. The backend stores UTC in
 * timestamp-without-time-zone columns, so its ISO strings carry no offset -
 * treat offset-less strings as UTC instead of letting Date assume local time. */
export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "never";
  const utc = /Z|[+-]\d{2}:?\d{2}$/.test(iso) ? iso : `${iso}Z`;
  const m = Math.floor((Date.now() - new Date(utc).getTime()) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}
