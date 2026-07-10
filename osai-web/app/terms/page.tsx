import Link from "next/link";

export default function TermsPage() {
  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "72px 24px", lineHeight: 1.7 }}>
      <Link href="/login">Back to sign in</Link>
      <h1>Terms of Service</h1>
      <p>Sheldon AI provides organization knowledge, automation, and approval tools. Use the service only for data you are authorized to access and actions you are authorized to request.</p>
      <p>Organization administrators are responsible for configuring access, reviewing proposed actions, and maintaining the accuracy of connected data sources.</p>
      <p>These terms are an interim product notice and will be replaced by the organization&apos;s executed service agreement before general availability.</p>
    </main>
  );
}
