with open("frontend/src/app/page.tsx", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Add import
if 'from "@/lib/supabase"' not in content:
    content = content.replace(
        'import ConnectAccountModal from "@/components/ConnectAccountModal";',
        'import ConnectAccountModal from "@/components/ConnectAccountModal";\nimport { isSupabaseConfigured, subscribeToAuth, signOutUser } from "@/lib/supabase";'
    )

# 2. Add Supabase auth listener into useEffect
old_use_effect_start = """  useEffect(() => {
    if (typeof window !== "undefined") {"""

new_use_effect_start = """  useEffect(() => {
    if (typeof window !== "undefined") {
      // 1. Real-time Supabase Auth listener
      if (isSupabaseConfigured) {
        subscribeToAuth((event, session) => {
          if (session?.user && session.access_token) {
            const user = session.user;
            setAuthToken(session.access_token);
            setTenantId(user.id);
            setUserProfile({
              uid: user.id,
              email: user.email,
              name: (user.user_metadata as any)?.name || user.email?.split("@")[0],
            });
            localStorage.setItem("xvibebot_auth_token", session.access_token);
            localStorage.setItem("xvibebot_tenant_id", user.id);
            if (user.email) localStorage.setItem("xvibebot_user_email", user.email);
            localStorage.removeItem("xvibebot_demo_mode");
            setAuthInitialized(true);
          } else if (event === "SIGNED_OUT") {
            setAuthToken("");
            setUserProfile(null);
            setTenantId("default");
            setDemoMode(false);
            setAuthInitialized(true);
          }
        });
      }"""

if old_use_effect_start in content and "subscribeToAuth" not in content:
    content = content.replace(old_use_effect_start, new_use_effect_start)

# 3. Add signOutUser to handleSignOut
old_signout = """  const handleSignOut = useCallback(async () => {
    try {
      await fetch("/api/auth/signout", { method: "POST" });
    } catch {}"""

new_signout = """  const handleSignOut = useCallback(async () => {
    try {
      if (isSupabaseConfigured) {
        await signOutUser();
      }
      await fetch("/api/auth/signout", { method: "POST" });
    } catch {}"""

if old_signout in content:
    content = content.replace(old_signout, new_signout)

with open("frontend/src/app/page.tsx", "w", encoding="utf-8") as f:
    f.write(content)

print("page.tsx updated with Supabase integration!")
