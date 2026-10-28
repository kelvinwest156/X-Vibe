with open('frontend/src/app/page.tsx', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add import
if 'import ConnectAccountModal' not in content:
    content = content.replace(
        'import AuthView from "@/components/AuthView";',
        'import AuthView from "@/components/AuthView";\nimport ConnectAccountModal from "@/components/ConnectAccountModal";'
    )

# 2. Add state
if 'const [connectModalOpen, setConnectModalOpen]' not in content:
    content = content.replace(
        'const [cookieOpen, setCookieOpen] = useState(false);',
        'const [cookieOpen, setCookieOpen] = useState(false);\n  const [connectModalOpen, setConnectModalOpen] = useState(false);'
    )

# 3. Update login function
old_login = '''  const login = async () => {
    setBusy((p) => ({ ...p, login: true }));
    try {
      const res = await apiFetch("/api/browser/launch-login", { method: "POST" });
      if (res.ok) {
        const d = await res.json();
        notify(d.message || "Browser session opened");
        setTimeout(refresh, 4000);
      } else {
        const errMsg = await extractApiError(res, "Failed to launch login browser");
        notify(errMsg, true);
      }
    } catch (err: any) {
      notify(err?.message || "Failed to launch browser", true);
    } finally {
      setBusy((p) => ({ ...p, login: false }));
    }
  };'''

new_login = '''  const login = () => {
    setConnectModalOpen(true);
  };'''

if old_login in content:
    content = content.replace(old_login, new_login)
else:
    print('Warning: old_login exact match not found')

# 4. Update onLoginWithX
content = content.replace(
    'onLoginWithX={login}',
    'onLoginWithX={() => { setDemoMode(true); setConnectModalOpen(true); }}'
)

# 5. Make desktop account pill open connect modal
old_pill = '''            {/* Account pill */}
            {status?.is_logged_in ? (
              <div className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white dark:bg-[#202020] border border-slate-200 dark:border-[#2E2E2E] text-xs shadow-2xs">
                <span className="relative flex h-2 w-2 shrink-0">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="font-semibold text-slate-800 dark:text-[#E5E5E5] max-w-[80px] sm:max-w-[120px] truncate">
                  {status.linked_username || "Linked"}
                </span>
                <button
                  onClick={checkSession}
                  disabled={busy.session}
                  title="Re-check session"
                  className="text-slate-400 hover:text-slate-700 dark:hover:text-white ml-0.5 transition-colors shrink-0"
                >
                  {busy.session ? <Spin className="w-3 h-3" /> : <RefreshCw className="w-3 h-3" />}
                </button>
              </div>'''

new_pill = '''            {/* Account pill */}
            {status?.is_logged_in ? (
              <button
                type="button"
                onClick={() => setConnectModalOpen(true)}
                title="Manage connected X account"
                className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white dark:bg-[#202020] border border-slate-200 dark:border-[#2E2E2E] text-xs shadow-2xs hover:border-slate-300 dark:hover:border-[#383838] transition-colors cursor-pointer text-left"
              >
                <span className="relative flex h-2 w-2 shrink-0">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
                </span>
                <span className="font-semibold text-slate-800 dark:text-[#E5E5E5] max-w-[80px] sm:max-w-[120px] truncate">
                  {status.linked_username || "Linked"}
                </span>
              </button>'''

if old_pill in content:
    content = content.replace(old_pill, new_pill)
else:
    print('Warning: old_pill exact match not found')

# 6. Update mobile action strip to open connect modal when clicked
old_mobile_btn = '''          {status?.is_logged_in ? (
            <button onClick={checkSession} disabled={busy.session} className="btn !h-10 text-xs justify-center">
              {busy.session ? <Spin /> : <span className="w-2 h-2 rounded-full bg-emerald-500" />}
              <span className="truncate">{status.linked_username || "Linked"}</span>
            </button>'''

new_mobile_btn = '''          {status?.is_logged_in ? (
            <button type="button" onClick={() => setConnectModalOpen(true)} className="btn !h-10 text-xs justify-center">
              <span className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="truncate">{status.linked_username || "Linked"}</span>
            </button>'''

if old_mobile_btn in content:
    content = content.replace(old_mobile_btn, new_mobile_btn)
else:
    print('Warning: old_mobile_btn exact match not found')

# 7. Add ConnectAccountModal before closing div
modal_markup = '''      {/* Connect Account Modal */}
      <ConnectAccountModal
        isOpen={connectModalOpen}
        onClose={() => setConnectModalOpen(false)}
        isLoggedIn={Boolean(status?.is_logged_in)}
        linkedUsername={status?.linked_username}
        onSessionUpdated={() => {
          refresh();
          loadHistory();
        }}
        apiFetch={apiFetch}
        notify={notify}
      />
    </div>
  );
}'''

if 'isOpen={connectModalOpen}' not in content:
    content = content.replace('    </div>\n  );\n}', modal_markup)

with open('frontend/src/app/page.tsx', 'w', encoding='utf-8') as f:
    f.write(content)

print('SUCCESS')
