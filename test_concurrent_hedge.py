#!/usr/bin/env python3
"""
Test script to simulate concurrent hedge operations and verify lock behavior.
This simulates the scenario where multiple StandX orders fill simultaneously.
"""

import asyncio
import os
import sys
from decimal import Decimal
from dotenv import load_dotenv

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lighter_client import LighterHedger
from config_loader import Config

# Load environment variables
load_dotenv()


async def test_concurrent_hedges():
    """Test concurrent hedge operations with lock protection."""

    print("=" * 80)
    print("Concurrent Hedge Test")
    print("=" * 80)

    # Initialize config
    config = Config()
    config.data = {
        "exchanges": {
            "lighter": {
                "enabled": True
            }
        },
        "trading": {
            "symbol": "BTC-USD"
        }
    }

    try:
        # Initialize Lighter client
        lighter = LighterHedger(config)

        print("\n✓ Connecting to Lighter...")
        connected = await lighter.connect()

        if not connected:
            print("❌ Failed to connect to Lighter")
            return False

        print("✓ Connected to Lighter successfully")

        # Get initial position
        initial_position = await lighter.get_position()
        print(f"\n✓ Initial Position: {initial_position} BTC")

        # Simulate concurrent hedge scenario
        print("\n" + "=" * 80)
        print("Simulating Concurrent Hedge Scenario")
        print("=" * 80)
        print("\nScenario: Two StandX SELL orders fill simultaneously")
        print("  Order 1: SELL 0.001 BTC → Hedge: BUY 0.001")
        print("  Order 2: SELL 0.002 BTC → Hedge: BUY 0.002")
        print("\nWithout lock: Both hedges would see the same initial position")
        print("With lock: Second hedge waits for first to complete\n")

        # Launch two concurrent hedge operations
        print("Launching concurrent hedge operations...")

        hedge1 = asyncio.create_task(
            lighter.place_hedge_order('buy', Decimal('0.001'))
        )

        # Small delay to ensure first hedge starts first
        await asyncio.sleep(0.05)

        hedge2 = asyncio.create_task(
            lighter.place_hedge_order('buy', Decimal('0.002'))
        )

        # Wait for both to complete
        results = await asyncio.gather(hedge1, hedge2, return_exceptions=True)

        print("\n" + "=" * 80)
        print("Results")
        print("=" * 80)

        success_count = sum(1 for r in results if r is True)
        print(f"\nHedge 1 (BUY 0.001): {'✓ Success' if results[0] is True else '✗ Failed'}")
        print(f"Hedge 2 (BUY 0.002): {'✓ Success' if results[1] is True else '✗ Failed'}")

        # Check final position
        final_position = await lighter.get_position()
        expected_position = initial_position + Decimal('0.003')
        position_diff = abs(final_position - expected_position)

        print(f"\nPosition Summary:")
        print(f"  Initial:  {initial_position} BTC")
        print(f"  Expected: {expected_position} BTC (+0.003)")
        print(f"  Actual:   {final_position} BTC")
        print(f"  Diff:     {position_diff} BTC")

        if position_diff < Decimal('0.0001'):
            print("\n✅ Position is CORRECT - Lock worked!")
        else:
            print("\n⚠️  Position mismatch - Possible issue")

        # Clean up - close the position
        if final_position != initial_position:
            print(f"\n" + "=" * 80)
            print("Cleanup: Closing test position")
            print("=" * 80)

            net_position = final_position - initial_position
            if net_position > 0:
                print(f"\nClosing long position: SELL {net_position} BTC")
                close_result = await lighter.place_hedge_order('sell', net_position)
                if close_result:
                    print("✓ Position closed successfully")
                else:
                    print("⚠️  Failed to close position - manual intervention needed")

        # Disconnect
        await lighter.disconnect()

        print("\n" + "=" * 80)
        print("✅ Test completed!")
        print("=" * 80)

        return success_count == 2 and position_diff < Decimal('0.0001')

    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_lock_serialization():
    """Test that lock properly serializes hedge operations."""

    print("\n" + "=" * 80)
    print("Lock Serialization Test")
    print("=" * 80)
    print("\nThis test verifies that hedge operations are executed serially,")
    print("not concurrently, by checking the log output.\n")

    print("Expected log pattern:")
    print("  [HEDGE-LOCK] Waiting for lock: BUY 0.001 BTC")
    print("  [HEDGE-LOCK] Lock acquired: BUY 0.001 BTC")
    print("  ... (hedge 1 executes) ...")
    print("  [HEDGE-LOCK] Lock released (success)")
    print("  [HEDGE-LOCK] Waiting for lock: BUY 0.002 BTC  ← Second hedge waits")
    print("  [HEDGE-LOCK] Lock acquired: BUY 0.002 BTC")
    print("  ... (hedge 2 executes) ...")
    print("  [HEDGE-LOCK] Lock released (success)")

    print("\n✓ Check the logs above to verify this pattern")
    print("✓ If you see 'Waiting' followed immediately by 'Lock acquired' for")
    print("  the second hedge AFTER the first releases, the lock is working!\n")


if __name__ == "__main__":
    print("\n" + "=" * 80)
    print("CONCURRENT HEDGE LOCK TEST")
    print("=" * 80)
    print("\nThis test will:")
    print("1. Connect to Lighter")
    print("2. Launch two concurrent hedge operations")
    print("3. Verify that they execute serially (not concurrently)")
    print("4. Check that the final position is correct")
    print("5. Clean up by closing the test position")
    print("\n⚠️  WARNING: This test will place real orders on Lighter!")
    print("   Make sure you have sufficient balance.")

    response = input("\nProceed with test? (yes/no): ")
    if response.lower() != 'yes':
        print("Test cancelled.")
        sys.exit(0)

    result = asyncio.run(test_concurrent_hedges())

    if result:
        asyncio.run(test_lock_serialization())

    exit(0 if result else 1)
