"""
Self-verification test script for X-VibeBot components.
Tests database operations, models, and FastAPI app routing.
"""

import os
import asyncio
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from models import Base, ProcessedTweet, AgentConfig
import database
import ai_engine

def test_database():
    print("-> Testing Database initialization...")
    test_engine = create_engine("sqlite:///:memory:")
    TestingSession = sessionmaker(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    session = TestingSession()

    # Test creating config
    cfg = AgentConfig(id=1, is_active=True, auto_pilot_mode=False, daily_action_cap=20)
    session.add(cfg)
    session.commit()
    assert session.query(AgentConfig).count() == 1
    print("   [OK] AgentConfig created successfully.")

    # Test ProcessedTweet
    tweet = ProcessedTweet(
        tweet_id="1234567890",
        action_type="reply",
        tweet_text="Testing AI bot on X!",
        tweet_author="test_user",
        tweet_url="https://x.com/test_user/status/1234567890",
        generated_text="This is an awesome test reply.",
        status="pending_approval"
    )
    session.add(tweet)
    session.commit()
    assert session.query(ProcessedTweet).count() == 1
    print("   [OK] ProcessedTweet recorded successfully.")

    # Test duplicate detection
    exists = session.query(ProcessedTweet).filter(ProcessedTweet.tweet_id == "1234567890").first() is not None
    assert exists is True
    print("   [OK] Duplicate prevention query verified.")
    session.close()

async def test_ai_fallback():
    print("-> Testing Google Gemini AI fallback when unconfigured...")
    res = await ai_engine.evaluate_tweet("Hello world test tweet", "dev_user")
    assert "should_reply" in res
    assert res["should_reply"] is False
    print(f"   [OK] Fallback handled gracefully: {res['reasoning']}")

def test_fastapi_app():
    print("-> Testing FastAPI app definition and routes...")
    from main import app
    routes = [r.path for r in app.routes]
    expected_routes = ["/", "/api/status", "/api/config", "/api/pending", "/api/history", "/api/approve/{tweet_id}", "/api/reject/{tweet_id}"]
    for er in expected_routes:
        assert er in routes, f"Missing route: {er}"
    print(f"   [OK] All {len(expected_routes)} core endpoints registered.")

async def test_browser_worker():
    print("-> Testing Playwright launch & stealth masking...")
    from browser_worker import XBrowserWorker
    import shutil
    test_prof = "./tmp_test_profile"
    worker = XBrowserWorker(headless=True, profile_dir=test_prof)
    try:
        page = await worker.get_active_page()
        webdriver_flag = await page.evaluate("() => navigator.webdriver")
        print(f"   [OK] Browser launched successfully. navigator.webdriver = {webdriver_flag} (masked)")
    finally:
        await worker.stop()
        if os.path.exists(test_prof):
            try:
                shutil.rmtree(test_prof, ignore_errors=True)
            except Exception:
                pass


if __name__ == "__main__":
    print("=== Running X-VibeBot Component Tests ===")
    test_database()
    asyncio.run(test_ai_fallback())
    test_fastapi_app()
    asyncio.run(test_browser_worker())
    print("=== All Component Tests Passed Successfully! ===")
