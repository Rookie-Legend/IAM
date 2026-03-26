from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

class Database:
    client: AsyncIOMotorClient = None

db_state = Database()

def connect_to_mongo():
    db_state.client = AsyncIOMotorClient(settings.MONGO_URL)

def close_mongo_connection():
    if db_state.client:
        db_state.client.close()

async def get_database():
    return db_state.client[settings.DB_NAME]
