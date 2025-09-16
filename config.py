import os
from dotenv import load_dotenv

load_dotenv()

class Settings:
    # Deriv API configuration - using the correct endpoint
    DERIV_WS_URL = os.getenv("DERIV_WS_URL", "wss://ws.derivws.com/websockets/v3?app_id=1089")
    
    # Trading settings
    DEFAULT_SYMBOL = os.getenv("DEFAULT_SYMBOL", "R_100")
    DEFAULT_AMOUNT = float(os.getenv("DEFAULT_AMOUNT", "10"))
    
    # Server settings
    HOST = os.getenv("HOST", "0.0.0.0")
    PORT = int(os.getenv("PORT", "8000"))

settings = Settings()