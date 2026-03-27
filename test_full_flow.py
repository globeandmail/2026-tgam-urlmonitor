"""
Full end-to-end test: fake old content, detect changes on real pages, send real email.
"""
import monitor

print("=" * 60)
print("FULL FLOW TEST")
print("=" * 60)

# Step 1: Store fake "previous" content to simulate a change
print("\n1. Storing fake previous content...")
monitor.save_state({
    "HudsonsBay": "This is fake old content that will not match the real page.",
    "TRUCanada": "This is also fake old content for TRU Canada.",
})
print("   Done. Fake content saved.")

# Step 2: Run the full monitor (fetches real pages, detects changes, sends emails)
print("\n2. Running monitor (will fetch real pages and send emails)...")
print("-" * 60)
monitor.main()
print("-" * 60)

print("\n3. Check your inbox at dmcmillan@globeandmail.com for 2 emails!")
print("=" * 60)
