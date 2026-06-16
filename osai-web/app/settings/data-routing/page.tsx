import { redirect } from "next/navigation";

// Data Routing now lives alongside Integrations (one page, two tabs) so tiers and
// the tools they apply to are configured together.
export default function DataRoutingRedirect() {
  redirect("/integrations?tab=routing");
}
