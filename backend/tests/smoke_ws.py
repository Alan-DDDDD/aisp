"""快速 WS smoke：建 room、開 WS、送一句話、印出回的 AI suggestion。"""

import asyncio
import json

import httpx
import websockets

BASE = "http://localhost:8765"
WS_BASE = "ws://localhost:8765"


async def main() -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{BASE}/api/rooms", json={"workspace_id": "default"})
        r.raise_for_status()
        room = r.json()

    print("Room:", room["id"])

    async with websockets.connect(f"{WS_BASE}/ws/rooms/{room['id']}") as ws:
        await ws.send(json.dumps({"type": "user_message", "content": "70 歲可以申請車貸嗎？"}))

        for _ in range(3):
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            event = json.loads(raw)
            print(f"\n← {event['type']}")
            if event["type"] == "user_message":
                print("  ", event["message"]["content"])
            elif event["type"] == "ai_suggestion":
                print("   draft:", event["draft"][:80], "...")
                print("   trace steps:", len(event["trace"]["steps"]))
                for s in event["trace"]["steps"]:
                    print(f"     - {s['agent_id']} ({s['latency_ms']}ms)")
                break


if __name__ == "__main__":
    asyncio.run(main())
