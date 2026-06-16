import { redirect } from "next/navigation";

// Evals moved into Settings → Advanced to declutter the main navigation.
export default function EvalsPage() {
  redirect("/settings/advanced");
}
