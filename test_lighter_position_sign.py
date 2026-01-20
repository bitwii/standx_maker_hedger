#!/usr/bin/env python3
"""
Test script to verify Lighter position sign convention.
This will help us understand if position.position is signed correctly.
"""

import asyncio
import os
from decimal import Decimal
from dotenv import load_dotenv
from lighter import SignerClient, ApiClient, Configuration
import lighter

# Load environment variables
load_dotenv()


async def test_position_sign():
    """Test position sign after buy and sell orders."""

    # Get credentials from environment
    api_key_private_key = os.getenv('API_KEY_PRIVATE_KEY')
    account_index = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
    api_key_index = int(os.getenv('LIGHTER_API_KEY_INDEX', '0'))
    base_url = "https://mainnet.zklighter.elliot.ai"

    print("=" * 80)
    print("Lighter Position Sign Test")
    print("=" * 80)

    if not api_key_private_key:
        print("\n❌ Error: API_KEY_PRIVATE_KEY not set in environment")
        return False

    try:
        # Initialize Lighter client
        api_private_keys = {api_key_index: api_key_private_key}
        lighter_client = SignerClient(
            url=base_url,
            account_index=account_index,
            api_private_keys=api_private_keys,
        )

        # Create API client
        api_client = ApiClient(configuration=Configuration(host=base_url))
        account_api = lighter.AccountApi(api_client)

        # Get market configuration for BTC
        order_api = lighter.OrderApi(api_client)
        order_books = await order_api.order_books()

        btc_market = None
        for market in order_books.order_books:
            if market.symbol == "BTC":
                btc_market = market
                break

        if not btc_market:
            print("❌ BTC market not found")
            return False

        print(f"\n✓ BTC Market Configuration:")
        print(f"  Market ID: {btc_market.market_id}")
        print(f"  Symbol: {btc_market.symbol}")

        base_amount_multiplier = pow(10, btc_market.supported_size_decimals)
        price_multiplier = pow(10, btc_market.supported_price_decimals)

        # Function to get current position
        async def get_position():
            account_data = await account_api.account(
                by="index",
                value=str(account_index)
            )
            if not account_data or not account_data.accounts:
                return Decimal('0')

            for position in account_data.accounts[0].positions:
                if position.market_id == btc_market.market_id:
                    return Decimal(str(position.position))
            return Decimal('0')

        # Get initial position
        initial_position = await get_position()
        print(f"\n✓ Initial Position: {initial_position} BTC")

        # Get current orderbook
        orderbook = await order_api.order_book_orders(market_id=btc_market.market_id, limit=5)
        best_bid = Decimal(str(orderbook.bids[0].price))
        best_ask = Decimal(str(orderbook.asks[0].price))

        print(f"\n✓ Current Market Prices:")
        print(f"  Best Bid: ${best_bid:,.2f}")
        print(f"  Best Ask: ${best_ask:,.2f}")

        # Test 1: Place a small BUY order
        print(f"\n" + "=" * 80)
        print("Test 1: BUY Order (is_ask=False)")
        print("=" * 80)

        buy_quantity = Decimal('0.001')  # Very small amount
        buy_price = int(best_ask * Decimal('1.05') * price_multiplier)

        print(f"\n  Placing BUY order: {buy_quantity} BTC")
        print(f"  is_ask=False (this should INCREASE position)")

        tx, tx_hash, err = await lighter_client.create_market_order(
            market_index=btc_market.market_id,
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=int(buy_quantity * base_amount_multiplier),
            avg_execution_price=buy_price,
            is_ask=False,
        )

        if err is not None:
            print(f"  ❌ Order failed: {err}")
            return False

        print(f"  ✓ Order submitted, waiting for fill...")
        await asyncio.sleep(1.5)

        position_after_buy = await get_position()
        buy_change = position_after_buy - initial_position

        print(f"\n  Position before: {initial_position}")
        print(f"  Position after:  {position_after_buy}")
        print(f"  Change:          {buy_change}")
        print(f"  Expected:        +{buy_quantity} (positive)")

        if buy_change > 0:
            print(f"  ✓ CORRECT: BUY increased position (is_ask=False works correctly)")
        else:
            print(f"  ❌ WRONG: BUY decreased position (is_ask=False is inverted!)")

        # Test 2: Place a small SELL order to close
        print(f"\n" + "=" * 80)
        print("Test 2: SELL Order (is_ask=True)")
        print("=" * 80)

        sell_quantity = buy_quantity
        sell_price = int(best_bid * Decimal('0.95') * price_multiplier)

        print(f"\n  Placing SELL order: {sell_quantity} BTC")
        print(f"  is_ask=True (this should DECREASE position)")

        tx, tx_hash, err = await lighter_client.create_market_order(
            market_index=btc_market.market_id,
            client_order_index=int(asyncio.get_event_loop().time() * 1000) % 1000000,
            base_amount=int(sell_quantity * base_amount_multiplier),
            avg_execution_price=sell_price,
            is_ask=True,
        )

        if err is not None:
            print(f"  ❌ Order failed: {err}")
            return False

        print(f"  ✓ Order submitted, waiting for fill...")
        await asyncio.sleep(1.5)

        position_after_sell = await get_position()
        sell_change = position_after_sell - position_after_buy

        print(f"\n  Position before: {position_after_buy}")
        print(f"  Position after:  {position_after_sell}")
        print(f"  Change:          {sell_change}")
        print(f"  Expected:        -{sell_quantity} (negative)")

        if sell_change < 0:
            print(f"  ✓ CORRECT: SELL decreased position (is_ask=True works correctly)")
        else:
            print(f"  ❌ WRONG: SELL increased position (is_ask=True is inverted!)")

        # Summary
        print(f"\n" + "=" * 80)
        print("Summary")
        print("=" * 80)

        if buy_change > 0 and sell_change < 0:
            print("\n✅ Position signs are CORRECT:")
            print("   - is_ask=False (BUY) increases position ✓")
            print("   - is_ask=True (SELL) decreases position ✓")
        elif buy_change < 0 and sell_change > 0:
            print("\n❌ Position signs are INVERTED:")
            print("   - is_ask=False (BUY) decreases position ✗")
            print("   - is_ask=True (SELL) increases position ✗")
            print("\n🔧 FIX: Invert the is_ask parameter in lighter_client.py:")
            print("   is_ask = False if side.lower() == 'sell' else True")
        else:
            print("\n⚠️  Unexpected behavior - manual investigation needed")

        # Close API client
        await api_client.close()

        print(f"\n" + "=" * 80)
        print("✅ Test completed!")
        print("=" * 80)

        return True

    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_position_sign())
    exit(0 if result else 1)
