import { redirect } from "next/navigation";

// Search has been merged into Ask Sheldon AI - both perform the same cited retrieval.
// This route now redirects so existing links and bookmarks keep working.
export default function SearchPage() {
  redirect("/ask");
}
