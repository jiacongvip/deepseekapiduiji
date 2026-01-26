import asyncio
import json
from src.pool.fetcher import DoubaoAutomator

async def main():
    print("Fetching session...")
    automator = DoubaoAutomator()
    # 使用手动模式
    session_data = await automator.run_automation(manual=True)
    
    print("Session fetched successfully.")
    
    # Save to session.json
    try:
        with open('session.json', 'w', encoding='utf-8') as f:
            json.dump([session_data], f, ensure_ascii=False, indent=4)
        print("Session saved to session.json")
    except Exception as e:
        print(f"Error saving session: {e}")

if __name__ == "__main__":
    asyncio.run(main())