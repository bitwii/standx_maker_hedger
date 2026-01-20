#!/usr/bin/env python3
"""
Test script to verify Lighter price calculation logic.
"""

import asyncio
import os
from decimal import Decimal
from dotenv import load_dotenv
from lighter import SignerClient, ApiClient, Configuration
import lighter

# Load environment variables
load_dotenv()


async def test_price_calculation():
    """Test price calculation for market orders."""

    # Get credentials from environment
    api_key_private_key = os.getenv('API_KEY_PRIVATE_KEY')
    account_index = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
    api_key_index = int(os.getenv('LIGHTER_API_KEY_INDEX', '0'))
    base_url = "https://mainnet.zklighter.elliot.ai"

    print("=" * 80)
    print("Lighter Price Calculation Test")
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
        print(f"  Supported Size Decimals: {btc_market.supported_size_decimals}")
        print(f"  Supported Price Decimals: {btc_market.supported_price_decimals}")

        base_amount_multiplier = pow(10, btc_market.supported_size_decimals)
        price_multiplier = pow(10, btc_market.supported_price_decimals)

        print(f"  Base Amount Multiplier: {base_amount_multiplier}")
        print(f"  Price Multiplier: {price_multiplier}")

        # Get current orderbook
        print(f"\n✓ Fetching BTC orderbook...")
        orderbook = await order_api.order_book_orders(market_id=btc_market.market_id, limit=5)

        if not orderbook or not orderbook.bids or not orderbook.asks:
            print("❌ Empty orderbook")
            return False

        # Get best bid and ask
        best_bid_str = orderbook.bids[0].price
        best_ask_str = orderbook.asks[0].price

        print(f"\n✓ Current Market Prices:")
        print(f"  Best Bid (string): '{best_bid_str}'")
        print(f"  Best Ask (string): '{best_ask_str}'")

        # Convert to Decimal (current method)
        best_bid_decimal = Decimal(str(best_bid_str))
        best_ask_decimal = Decimal(str(best_ask_str))

        print(f"  Best Bid (Decimal): {best_bid_decimal}")
        print(f"  Best Ask (Decimal): {best_ask_decimal}")

        # Test SELL order price calculation
        print(f"\n" + "=" * 80)
        print("Testing SELL Order Price Calculation")
        print("=" * 80)

        side = "sell"
        is_ask = True
        expected_price = best_bid_decimal  # For sell, use best_bid

        print(f"\n  Order Side: {side}")
        print(f"  is_ask: {is_ask}")
        print(f"  Expected Price (Decimal): {expected_price}")

        # Method 1: Current implementation (WRONG?)
        slippage_multiplier_1 = Decimal('0.95')
        avg_execution_price_1 = int(expected_price * slippage_multiplier_1 * price_multiplier)

        print(f"\n  Method 1 (Current Implementation):")
        print(f"    Slippage Multiplier: {slippage_multiplier_1}")
        print(f"    Calculation: int({expected_price} * {slippage_multiplier_1} * {price_multiplier})")
        print(f"    avg_execution_price: {avg_execution_price_1}")
        print(f"    Represents Price: ${avg_execution_price_1 / price_multiplier:,.2f}")

        # Method 2: SDK style (remove decimal point first)
        price_int = int(best_bid_str.replace(".", ""))
        slippage_multiplier_2 = 0.95
        avg_execution_price_2 = round(price_int * slippage_multiplier_2)

        print(f"\n  Method 2 (SDK Style - remove decimal point):")
        print(f"    Price String: '{best_bid_str}'")
        print(f"    After removing '.': '{best_bid_str.replace('.', '')}'")
        print(f"    Price Int: {price_int}")
        print(f"    Slippage Multiplier: {slippage_multiplier_2}")
        print(f"    Calculation: round({price_int} * {slippage_multiplier_2})")
        print(f"    avg_execution_price: {avg_execution_price_2}")

        # Try to figure out what price this represents
        # If price_multiplier is 10, then we need to figure out the decimal places
        print(f"\n  Trying to decode Method 2 price:")
        print(f"    If we divide by 10^1: ${avg_execution_price_2 / 10:,.2f}")
        print(f"    If we divide by 10^2: ${avg_execution_price_2 / 100:,.2f}")
        print(f"    If we divide by 10^3: ${avg_execution_price_2 / 1000:,.2f}")
        print(f"    If we divide by 10^4: ${avg_execution_price_2 / 10000:,.2f}")
        print(f"    If we divide by 10^5: ${avg_execution_price_2 / 100000:,.2f}")

        # Test BUY order price calculation
        print(f"\n" + "=" * 80)
        print("Testing BUY Order Price Calculation")
        print("=" * 80)

        side = "buy"
        is_ask = False
        expected_price = best_ask_decimal  # For buy, use best_ask

        print(f"\n  Order Side: {side}")
        print(f"  is_ask: {is_ask}")
        print(f"  Expected Price (Decimal): {expected_price}")

        # Method 1: Current implementation
        slippage_multiplier_1 = Decimal('1.05')
        avg_execution_price_1 = int(expected_price * slippage_multiplier_1 * price_multiplier)

        print(f"\n  Method 1 (Current Implementation):")
        print(f"    Slippage Multiplier: {slippage_multiplier_1}")
        print(f"    Calculation: int({expected_price} * {slippage_multiplier_1} * {price_multiplier})")
        print(f"    avg_execution_price: {avg_execution_price_1}")
        print(f"    Represents Price: ${avg_execution_price_1 / price_multiplier:,.2f}")

        # Method 2: SDK style
        price_int = int(best_ask_str.replace(".", ""))
        slippage_multiplier_2 = 1.05
        avg_execution_price_2 = round(price_int * slippage_multiplier_2)

        print(f"\n  Method 2 (SDK Style - remove decimal point):")
        print(f"    Price String: '{best_ask_str}'")
        print(f"    After removing '.': '{best_ask_str.replace('.', '')}'")
        print(f"    Price Int: {price_int}")
        print(f"    Slippage Multiplier: {slippage_multiplier_2}")
        print(f"    Calculation: round({price_int} * {slippage_multiplier_2})")
        print(f"    avg_execution_price: {avg_execution_price_2}")

        print(f"\n  Trying to decode Method 2 price:")
        print(f"    If we divide by 10^1: ${avg_execution_price_2 / 10:,.2f}")
        print(f"    If we divide by 10^2: ${avg_execution_price_2 / 100:,.2f}")
        print(f"    If we divide by 10^3: ${avg_execution_price_2 / 1000:,.2f}")
        print(f"    If we divide by 10^4: ${avg_execution_price_2 / 10000:,.2f}")
        print(f"    If we divide by 10^5: ${avg_execution_price_2 / 100000:,.2f}")

        # Summary
        print(f"\n" + "=" * 80)
        print("Summary")
        print("=" * 80)
        print(f"\nFor SELL order at market price ~${best_bid_decimal:,.2f}:")
        print(f"  Method 1 gives: {avg_execution_price_1} (represents ${avg_execution_price_1 / price_multiplier:,.2f})")
        print(f"  Method 2 gives: {avg_execution_price_2}")
        print(f"  Difference: {abs(avg_execution_price_2 - avg_execution_price_1)}")
        print(f"  Ratio: {avg_execution_price_2 / avg_execution_price_1 if avg_execution_price_1 != 0 else 'N/A'}")

        # Close API client
        await api_client.close()

        print(f"\n" + "=" * 80)
        print("✅ Test completed successfully!")
        print("=" * 80)

        return True

    except Exception as e:
        print(f"\n❌ Error during test: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    result = asyncio.run(test_price_calculation())
    exit(0 if result else 1)
