"use client";

import { useState, useEffect, type ReactNode } from "react";
import { login, onboardOrg } from "../lib/api";

type AuthWrapperProps = {
  children: ReactNode;
};

export default function AuthWrapper({ children }: AuthWrapperProps) {
  const [token, setToken] = useState<string | null>(null);
  const [orgId, setOrgId] = useState<string | null>(null);
  const [orgName, setOrgName] = useState<string | null>(null);
  const [userEmail, setUserEmail] = useState<string | null>(null);
  const [userName, setUserName] = useState<string | null>(null);

  const [isLogin, setIsLogin] = useState(true);

  // Login fields
  const [emailInput, setEmailInput] = useState("");

  // Onboard fields
  const [orgNameInput, setOrgNameInput] = useState("");
  const [adminEmailInput, setAdminEmailInput] = useState("");
  const [adminNameInput, setAdminNameInput] = useState("");

  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const savedToken = localStorage.getItem("osai_token");
    const savedOrgId = localStorage.getItem("osai_org_id");
    const savedOrgName = localStorage.getItem("osai_org_name");
    const savedUserEmail = localStorage.getItem("osai_user_email");
    const savedUserName = localStorage.getItem("osai_user_name");

    if (savedToken && savedOrgId) {
      setToken(savedToken);
      setOrgId(savedOrgId);
      setOrgName(savedOrgName);
      setUserEmail(savedUserEmail);
      setUserName(savedUserName);
    }
  }, []);

  const enterDemoMode = () => {
    localStorage.setItem("osai_token", "demo-token");
    localStorage.setItem("osai_org_id", "demo-org");
    localStorage.setItem("osai_org_name", "Intellact AI");
    localStorage.setItem("osai_user_email", "admin@intellactai.com");
    localStorage.setItem("osai_user_name", "Admin");
    setToken("demo-token");
    setOrgId("demo-org");
    setOrgName("Intellact AI");
    setUserEmail("admin@intellactai.com");
    setUserName("Admin");
  };

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const session = await login({ email: emailInput });
      localStorage.setItem("osai_token", session.token);
      localStorage.setItem("osai_org_id", session.org_id);
      localStorage.setItem("osai_user_email", emailInput);
      localStorage.setItem("osai_org_name", session.org_id === "demo-org" ? "OSAI Demo Org" : `Org: ${session.org_id}`);
      localStorage.setItem("osai_user_name", "Administrator");

      setToken(session.token);
      setOrgId(session.org_id);
      setOrgName(session.org_id === "demo-org" ? "OSAI Demo Org" : `Org: ${session.org_id}`);
      setUserEmail(emailInput);
      setUserName("Administrator");
      window.location.reload();
    } catch (err: any) {
      setError(err.message || "Failed to log in.");
    } finally {
      setLoading(false);
    }
  };

  const handleOnboard = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await onboardOrg({
        name: orgNameInput,
        admin_email: adminEmailInput,
        admin_display_name: adminNameInput,
      });

      // Auto login as the admin
      const session = await login({ email: adminEmailInput });
      localStorage.setItem("osai_token", session.token);
      localStorage.setItem("osai_org_id", session.org_id);
      localStorage.setItem("osai_user_email", adminEmailInput);
      localStorage.setItem("osai_org_name", res.name);
      localStorage.setItem("osai_user_name", res.admin_display_name);

      setToken(session.token);
      setOrgId(session.org_id);
      setOrgName(res.name);
      setUserEmail(adminEmailInput);
      setUserName(res.admin_display_name);
      window.location.reload();
    } catch (err: any) {
      setError(err.message || "Failed to onboard organization.");
    } finally {
      setLoading(false);
    }
  };

  const handleLogout = () => {
    localStorage.clear();
    setToken(null);
    setOrgId(null);
    setOrgName(null);
    setUserEmail(null);
    setUserName(null);
    window.location.reload();
  };

  if (!token) {
    return (
      <div className="auth-wrapper-container">
        <div className="auth-card">
          <div className="auth-header">
            <h1>OSAI</h1>
            <p>Enterprise operating layer for company context</p>
          </div>

          <div className="auth-tabs">
            <button
              onClick={() => {
                setIsLogin(true);
                setError(null);
              }}
              className={`auth-tab ${isLogin ? "active" : ""}`}
            >
              Sign In
            </button>
            <button
              onClick={() => {
                setIsLogin(false);
                setError(null);
              }}
              className={`auth-tab ${!isLogin ? "active" : ""}`}
            >
              Onboard Org
            </button>
          </div>

          {/* Demo bypass */}
          <button
            type="button"
            onClick={enterDemoMode}
            style={{
              width: "100%",
              padding: "11px",
              borderRadius: 9999,
              background: "linear-gradient(135deg, #4f83b1 0%, #c084fc 100%)",
              border: "none",
              color: "#fff",
              fontWeight: 700,
              fontSize: 14,
              cursor: "pointer",
              marginBottom: 4,
              boxShadow: "0 4px 16px rgba(192,132,252,0.25)",
            }}
          >
            ✨ Enter Demo Mode
          </button>
          <p style={{ textAlign: "center", fontSize: 11, color: "#64748b", margin: "0 0 4px" }}>
            or sign in with your credentials below
          </p>

          {error && <div className="auth-error">{error}</div>}

          {isLogin ? (
            <form onSubmit={handleLogin} className="auth-form">
              <div className="form-group">
                <label>Email Address</label>
                <input
                  type="email"
                  required
                  placeholder="name@company.com"
                  className="auth-input"
                  value={emailInput}
                  onChange={(e) => setEmailInput(e.target.value)}
                />
              </div>
              <button type="submit" disabled={loading} className="auth-btn">
                {loading ? "Signing in..." : "Continue"}
              </button>
            </form>
          ) : (
            <form onSubmit={handleOnboard} className="auth-form">
              <div className="form-group">
                <label>Organization Name</label>
                <input
                  type="text"
                  required
                  placeholder="Acme Corp"
                  className="auth-input"
                  value={orgNameInput}
                  onChange={(e) => setOrgNameInput(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>Admin Name</label>
                <input
                  type="text"
                  required
                  placeholder="Jane Doe"
                  className="auth-input"
                  value={adminNameInput}
                  onChange={(e) => setAdminNameInput(e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>Admin Email</label>
                <input
                  type="email"
                  required
                  placeholder="admin@acme.com"
                  className="auth-input"
                  value={adminEmailInput}
                  onChange={(e) => setAdminEmailInput(e.target.value)}
                />
              </div>
              <button type="submit" disabled={loading} className="auth-btn">
                {loading ? "Provisioning..." : "Onboard Organization"}
              </button>
            </form>
          )}
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
