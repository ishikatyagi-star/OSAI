import Link from "next/link";

export default function PrivacyPage() {
  return (
    <main style={{ maxWidth: 760, margin: "0 auto", padding: "72px 24px", lineHeight: 1.7 }}>
      <Link href="/login">Back to sign in</Link>
      <h1>Privacy Policy</h1>
      <p>Sheldon AI processes the content that an organization connects or submits in order to provide search, automation, and approval workflows.</p>
      <p>Access is scoped to the organization and user permissions configured in the product. Administrators can disconnect integrations and control membership.</p>
      <p>This interim notice will be replaced by the organization&apos;s final privacy policy before general availability.</p>
    </main>
  );
}
