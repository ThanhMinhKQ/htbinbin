import asyncio
from app.db.session import SessionLocal
from app.api.inventory.exports import get_request_tickets

async def test():
    db = SessionLocal()
    try:
        print("--- Testing get_request_tickets for B1 ---")
        # Assuming B1 has ID 1 based on previous debug
        dest_wh_id = 1 
        
        result = await get_request_tickets(
            dest_warehouse_id=dest_wh_id,
            page=1,
            per_page=10,
            db=db
        )
        
        print(f"Total Records: {result['totalRecords']}")
        print(f"Records Fetched: {len(result['records'])}")
        
        if len(result['records']) == 0 and result['totalRecords'] > 0:
            print("!!! BUG REPRODUCED !!!")
        else:
            print("Status: Normal")
            
        print("First Record Data:", result['records'][0] if result['records'] else "None")

    except Exception as e:
        print(f"Error: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    asyncio.run(test())
