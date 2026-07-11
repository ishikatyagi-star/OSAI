import { redirect } from "next/navigation";

// Team Board has been merged into the Decision Log. Its unique value - surfacing
// tasks Sheldon found that aren't tracked in your tools - is now the "Sheldon-identified"
// filter there. This route redirects so existing links keep working.
export default function BoardPage() {
  redirect("/decisions?source=osai");
}
