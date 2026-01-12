"""
Test script to inspect Lighter account data structure
检查 Lighter 账户数据结构
"""
import os
import asyncio
import logging
from dotenv import load_dotenv
import lighter
from lighter import ApiClient, Configuration, SignerClient

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def inspect_account_data():
    """检查账户数据结构"""
    try:
        # Get credentials
        api_key_private_key = os.getenv('API_KEY_PRIVATE_KEY')
        account_index = int(os.getenv('LIGHTER_ACCOUNT_INDEX', '0'))
        api_key_index = int(os.getenv('LIGHTER_API_KEY_INDEX', '0'))
        base_url = "https://mainnet.zklighter.elliot.ai"

        # Initialize clients
        api_client = ApiClient(configuration=Configuration(host=base_url))
        account_api = lighter.AccountApi(api_client)

        logger.info(f"查询账户索引: {account_index}")

        # Get account data
        account_data = await account_api.account(
            by="index",
            value=str(account_index)
        )

        logger.info("\n=== Account Data Structure ===")
        logger.info(f"Type: {type(account_data)}")
        logger.info(f"Dir: {[attr for attr in dir(account_data) if not attr.startswith('_')]}")

        if hasattr(account_data, 'accounts') and account_data.accounts:
            account = account_data.accounts[0]
            logger.info("\n=== Account Object ===")
            logger.info(f"Type: {type(account)}")

            # List all attributes
            attrs = [attr for attr in dir(account) if not attr.startswith('_')]
            logger.info(f"\nAll attributes: {attrs}")

            # Print important fields
            logger.info("\n=== Account Fields ===")
            for attr in attrs:
                try:
                    value = getattr(account, attr)
                    if not callable(value):
                        logger.info(f"{attr}: {value}")
                except Exception as e:
                    logger.info(f"{attr}: <error: {e}>")

        await api_client.close()

    except Exception as e:
        logger.error(f"Error: {e}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(inspect_account_data())
