with open("frontend/src/app/page.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add authInitialized state
old_auth_state = """  const [authToken, setAuthToken] = useState<string>("");"""
new_auth_state = """  const [authToken, setAuthToken] = useState<string>("");
  const [authInitialized, setAuthInitialized] = useState<boolean>(false);"""

if old_auth_state in content and "authInitialized" not in content:
    content = content.replace(old_auth_state, new_auth_state)

# 2. Update initial useEffect to restore demoMode and set authInitialized
old_effect = """      const savedToken = localStorage.getItem("xvibebot_auth_token");
      const savedTenant = localStorage.getItem("xvibebot_tenant_id");
      const savedEmail = localStorage.getItem("xvibebot_user_email");
      if (savedToken) setAuthToken(savedToken);
      if (savedTenant) setTenantId(savedTenant);
      if (savedEmail) setUserProfile({ email: savedEmail, name: savedEmail.split("@")[0] });

      // Verify token with backend
      if (savedToken) {
        fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${savedToken}` },
        })
          .then((r) => (r.ok ? r.json() : null))
          .then((d) => {
            if (d && d.email) {
              setUserProfile({ email: d.email, name: d.name, uid: d.uid });
              if (d.tenant_id) setTenantId(d.tenant_id);
            }
          })
          .catch(() => {});
      }"""

new_effect = """      const savedToken = localStorage.getItem("xvibebot_auth_token");
      const savedTenant = localStorage.getItem("xvibebot_tenant_id");
      const savedEmail = localStorage.getItem("xvibebot_user_email");
      const savedDemo = localStorage.getItem("xvibebot_demo_mode");

      if (savedDemo === "true") {
        setDemoMode(true);
      }
      if (savedToken) {
        setAuthToken(savedToken);
      }
      if (savedTenant) {
        setTenantId(savedTenant);
      }
      if (savedEmail) {
        setUserProfile({ email: savedEmail, name: savedEmail.split("@")[0] });
      }

      // Verify token with backend
      if (savedToken) {
        fetch("/api/auth/me", {
          headers: { Authorization: `Bearer ${savedToken}` },
        })
          .then((r) => {
            if (r.ok) return r.json();
            if (r.status === 401) {
              localStorage.removeItem("xvibebot_auth_token");
              localStorage.removeItem("xvibebot_tenant_id");
              localStorage.removeItem("xvibebot_user_email");
              setAuthToken("");
              setUserProfile(null);
            }
            return null;
          })
          .then((d) => {
            if (d && d.email) {
              setUserProfile({ email: d.email, name: d.name, uid: d.uid });
              if (d.tenant_id) setTenantId(d.tenant_id);
            }
          })
          .catch(() => {})
          .finally(() => {
            setAuthInitialized(true);
          });
      } else {
        setAuthInitialized(true);
      }"""

if old_effect in content:
    content = content.replace(old_effect, new_effect)

# 3. Update handleSignOut to clear demoMode and notify
old_signout = """  const handleSignOut = useCallback(async () => {
    try {
      await fetch("/api/auth/signout", { method: "POST" });
    } catch {}
    if (typeof window !== "undefined") {
      localStorage.removeItem("xvibebot_auth_token");
      localStorage.removeItem("xvibebot_tenant_id");
      localStorage.removeItem("xvibebot_user_email");
    }
    setAuthToken("");
    setUserProfile(null);
    setTenantId("default");
    setDemoMode(false);
  }, []);"""

new_signout = """  const handleSignOut = useCallback(async () => {
    try {
      await fetch("/api/auth/signout", { method: "POST" });
    } catch {}
    if (typeof window !== "undefined") {
      localStorage.removeItem("xvibebot_auth_token");
      localStorage.removeItem("xvibebot_tenant_id");
      localStorage.removeItem("xvibebot_user_email");
      localStorage.removeItem("xvibebot_demo_mode");
    }
    setAuthToken("");
    setUserProfile(null);
    setTenantId("default");
    setDemoMode(false);
    notify("Signed out of Creator Studio.");
  }, [notify]);

  const enterDemoMode = useCallback(() => {
    setDemoMode(true);
    if (typeof window !== "undefined") {
      localStorage.setItem("xvibebot_demo_mode", "true");
    }
  }, []);"""

if old_signout in content:
    content = content.replace(old_signout, new_signout)

# 4. Update AuthView guard
old_authview_guard = """  // If user is not authenticated and hasn't toggled demo mode, show AuthView!
  if (ready && !isUserAuthenticated) {
    return (
      <AuthView
        theme={theme}
        onToggleTheme={toggleTheme}
        onLoginWithX={() => { setDemoMode(true); setConnectModalOpen(true); }}
        onExploreDemo={() => setDemoMode(true)}
        busyLogin={busy.login}
        onAuthenticated={(user, token) => {
          const tId = user.uid || (user as any).tenant_id || "default";
          setTenantId(tId);
          setAuthToken(token);
          setUserProfile({ email: user.email || undefined, name: user.displayName || user.email?.split("@")[0], uid: user.uid });
          if (typeof window !== "undefined") {
            localStorage.setItem("xvibebot_auth_token", token);
            localStorage.setItem("xvibebot_tenant_id", tId);
            if (user.email) localStorage.setItem("xvibebot_user_email", user.email);
          }
          refresh();
        }}
      />
    );
  }"""

new_authview_guard = """  // Smooth loading splash while initializing stored authentication
  if (!authInitialized && !isUserAuthenticated) {
    return (
      <div className="min-h-screen bg-[#F8FAFC] dark:bg-[#121212] flex items-center justify-center">
        <div className="flex flex-col items-center gap-3 text-slate-500 dark:text-[#A3A3A3]">
          <Loader2 className="w-6 h-6 animate-spin text-neutral-900 dark:text-white" />
          <span className="text-xs font-medium">Loading Creator Studio...</span>
        </div>
      </div>
    );
  }

  // If user is not authenticated and hasn't toggled demo mode, show AuthView!
  if (!isUserAuthenticated) {
    return (
      <AuthView
        theme={theme}
        onToggleTheme={toggleTheme}
        onLoginWithX={() => {
          enterDemoMode();
          setConnectModalOpen(true);
        }}
        onExploreDemo={enterDemoMode}
        busyLogin={busy.login}
        onAuthenticated={(user, token) => {
          const tId = user.uid || (user as any).tenant_id || "default";
          setTenantId(tId);
          setAuthToken(token);
          setUserProfile({ email: user.email || undefined, name: user.displayName || user.email?.split("@")[0], uid: user.uid });
          if (typeof window !== "undefined") {
            localStorage.setItem("xvibebot_auth_token", token);
            localStorage.setItem("xvibebot_tenant_id", tId);
            if (user.email) localStorage.setItem("xvibebot_user_email", user.email);
            localStorage.removeItem("xvibebot_demo_mode");
          }
          refresh();
        }}
      />
    );
  }"""

if old_authview_guard in content:
    content = content.replace(old_authview_guard, new_authview_guard)

# 5. Add prominent Log Out button to header
old_profile_pill = """            {/* Multi-Tenant / User Profile pill */}
            {userProfile && (
              <div className="flex items-center gap-1.5 px-2 sm:px-2.5 h-8 rounded-lg bg-slate-100 dark:bg-[#222222] border border-slate-200/80 dark:border-[#2E2E2E] text-xs text-slate-700 dark:text-[#D4D4D4] shadow-2xs">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                <span className="hidden sm:inline font-medium sm:max-w-[120px] truncate" title={userProfile.email || tenantId}>
                  {userProfile.name || userProfile.email || "Workspace"}
                </span>
                <button
                  onClick={handleSignOut}
                  title="Sign out of studio account"
                  className="text-slate-400 hover:text-rose-500 ml-1 transition-colors"
                >
                  <LogOut className="w-3 h-3" />
                </button>
              </div>
            )}"""

new_profile_pill = """            {/* Multi-Tenant / User Profile pill */}
            {userProfile ? (
              <div className="flex items-center gap-2 px-2.5 h-8 rounded-lg bg-slate-100 dark:bg-[#202020] border border-slate-200/80 dark:border-[#2E2E2E] text-xs text-slate-700 dark:text-[#D4D4D4] shadow-2xs">
                <span className="w-2 h-2 rounded-full bg-emerald-500 shrink-0" />
                <span className="hidden sm:inline font-medium max-w-[120px] truncate" title={userProfile.email || tenantId}>
                  {userProfile.name || userProfile.email || "Creator"}
                </span>
              </div>
            ) : (
              <div className="hidden sm:flex items-center gap-1.5 px-2.5 h-8 rounded-lg bg-amber-500/10 border border-amber-500/20 text-xs text-amber-600 dark:text-amber-400 font-medium">
                <Sparkles className="w-3.5 h-3.5" />
                <span>Demo Mode</span>
              </div>
            )}

            {/* Dedicated Prominent Log Out Button (Always Available) */}
            <button
              type="button"
              onClick={handleSignOut}
              title="Log out of Creator Studio"
              className="flex items-center gap-1.5 px-2.5 h-8 rounded-lg text-xs font-medium text-slate-600 dark:text-[#A3A3A3] hover:text-rose-600 dark:hover:text-rose-400 hover:bg-rose-50 dark:hover:bg-rose-950/20 border border-slate-200 dark:border-[#2E2E2E] transition-all cursor-pointer"
            >
              <LogOut className="w-3.5 h-3.5 text-rose-500" />
              <span className="hidden sm:inline">Log Out</span>
            </button>"""

if old_profile_pill in content:
    content = content.replace(old_profile_pill, new_profile_pill)

# 6. Add Account & Session Section to Settings View
old_save_button = """                  {/* Save button */}
                  <button
                    onClick={() => saveSettings(false)}
                    disabled={busy.save}
                    className="btn btn-primary w-full justify-center !h-10 text-xs"
                  >
                    {busy.save ? <Spin /> : <CheckCircle2 className="w-4 h-4" />}
                    <span>{busy.save ? "Saving Settings..." : "Save Studio Configuration"}</span>
                  </button>"""

new_save_button = """                  {/* Account & Session Security Section */}
                  <div className="p-4 rounded-xl border border-slate-200 dark:border-[#262626] bg-slate-50/70 dark:bg-[#202020] space-y-3">
                    <div className="flex items-center justify-between">
                      <div className="space-y-0.5">
                        <span className="block text-xs font-semibold text-slate-900 dark:text-white">
                          Creator Account & Session
                        </span>
                        <span className="text-[11px] text-slate-500 dark:text-[#A3A3A3]">
                          {userProfile?.email ? `Signed in as ${userProfile.email}` : "Currently in Sneak Peek / Demo Mode"} · 365-day persistent session
                        </span>
                      </div>
                      <span className="text-[10px] font-medium px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-500/20">
                        Active
                      </span>
                    </div>
                    <div className="pt-1 flex items-center justify-between">
                      <span className="text-[11px] text-slate-400 font-mono">
                        Tenant ID: {tenantId}
                      </span>
                      <button
                        type="button"
                        onClick={handleSignOut}
                        className="btn !h-8 !px-3 text-xs text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-900/40 hover:bg-rose-50 dark:hover:bg-rose-950/30 flex items-center gap-1.5"
                      >
                        <LogOut className="w-3.5 h-3.5" />
                        <span>Sign Out of Studio</span>
                      </button>
                    </div>
                  </div>

                  {/* Save button */}
                  <button
                    onClick={() => saveSettings(false)}
                    disabled={busy.save}
                    className="btn btn-primary w-full justify-center !h-10 text-xs"
                  >
                    {busy.save ? <Spin /> : <CheckCircle2 className="w-4 h-4" />}
                    <span>{busy.save ? "Saving Settings..." : "Save Studio Configuration"}</span>
                  </button>"""

if old_save_button in content:
    content = content.replace(old_save_button, new_save_button)

with open("frontend/src/app/page.tsx", "w", encoding="utf-8") as f:
    f.write(content)

print("page.tsx updated with persistent session and logout button!")
