import { RecoveryScreen } from "@/components/recovery-screen";

export default function NotFound() {
  return (
    <RecoveryScreen
      title="This page does not exist"
      description="The link may be outdated, or the page may have moved."
    />
  );
}
