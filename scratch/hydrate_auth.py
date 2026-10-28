with open('frontend/src/app/page.tsx', 'r', encoding='utf-8') as f:
    text = f.read()

target = 'if (savedEmail) {\n        setUserProfile({ email: savedEmail, name: savedEmail.split("@")[0] });\n      }'
replacement = 'if (savedEmail) {\n        setUserProfile({ email: savedEmail, name: savedEmail.split("@")[0] });\n      }\n      setAuthInitialized(true);'

if target in text:
    text = text.replace(target, replacement, 1)
    with open('frontend/src/app/page.tsx', 'w', encoding='utf-8') as f:
        f.write(text)
    print("SUCCESS")
else:
    # Try with CRLF
    target_crlf = target.replace('\n', '\r\n')
    replacement_crlf = replacement.replace('\n', '\r\n')
    if target_crlf in text:
        text = text.replace(target_crlf, replacement_crlf, 1)
        with open('frontend/src/app/page.tsx', 'w', encoding='utf-8') as f:
            f.write(text)
        print("SUCCESS CRLF")
    else:
        print("TARGET NOT FOUND")
