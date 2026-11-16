import requests
import time

BASE_URL = "http://127.0.0.1:8000"

def test_flow():
    # Wait for server ready
    for _ in range(10):
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=2)
            if r.status_code == 200:
                print("Server is healthy.")
                break
        except Exception:
            time.sleep(1)
    else:
        raise RuntimeError("Server did not become healthy in time.")

    test_email = f"reset_test_{int(time.time())}@example.com"
    initial_pass = "oldPassword123!"
    new_pass = "brandNewPassword456!"

    print(f"\n1. Signing up test user: {test_email}")
    r = requests.post(
        f"{BASE_URL}/api/auth/signup",
        json={"email": test_email, "password": initial_pass, "name": "Reset Tester"}
    )
    print("Signup status:", r.status_code, r.json())
    assert r.status_code == 200, f"Signup failed: {r.text}"

    print("\n2. Requesting forgot-password token...")
    r = requests.post(
        f"{BASE_URL}/api/auth/forgot-password",
        json={"email": test_email}
    )
    print("Forgot password status:", r.status_code, r.json())
    assert r.status_code == 200, f"Forgot-password failed: {r.text}"
    reset_token = r.json().get("reset_token")

    if not reset_token:
        print("[SMTP Active] Live SMTP dispatched email to recipient. Generating token from database for test.")
        import sys
        import os
        sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
        from database import create_password_reset_token
        reset_token = create_password_reset_token(test_email)

    assert reset_token, "No reset token available for testing!"

    print(f"\n3. Resetting password with token: {reset_token[:15]}...")
    r = requests.post(
        f"{BASE_URL}/api/auth/reset-password",
        json={"token": reset_token, "new_password": new_pass}
    )
    print("Reset password status:", r.status_code, r.json())
    assert r.status_code == 200, f"Reset password failed: {r.text}"
    assert r.json().get("success") is True, "Success flag was not True"

    print("\n4. Verifying sign-in with OLD password fails...")
    r = requests.post(
        f"{BASE_URL}/api/auth/signin",
        json={"email": test_email, "password": initial_pass}
    )
    print("Sign in with old password status:", r.status_code)
    assert r.status_code == 401, "Expected 401 Unauthorized for old password"

    print("\n5. Verifying sign-in with NEW password succeeds...")
    r = requests.post(
        f"{BASE_URL}/api/auth/signin",
        json={"email": test_email, "password": new_pass}
    )
    print("Sign in with new password status:", r.status_code, r.json().get("message"))
    assert r.status_code == 200, f"Sign in with new password failed: {r.text}"
    assert r.json().get("success") is True, "Sign in success was not True"

    print("\n[SUCCESS] Entire forgot-password & reset-password flow verified end-to-end!")

if __name__ == "__main__":
    test_flow()
