import { redirect } from "next/navigation";

// Renamed to /analytics to end the /dashboard vs /dashboards confusion.
// Kept as a redirect so existing bookmarks still resolve.
export default function DashboardsRedirect() {
  redirect("/analytics");
}
