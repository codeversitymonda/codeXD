from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import asyncio
import uuid
import hashlib

# Import your actual trading components
try:
    from enhanced_trading_bot import get_user_bot, cleanup_inactive_bots
    from deriv_api import deriv_api
    
    print("✅ Enhanced trading bot loaded successfully")
except ImportError as e:
    print(f"⚠️ Import error: {e}")
    print("Using mock implementations for testing...")
    
    # Fallback mock classes if imports fail
    class MockTradingBot:
        def __init__(self, user_id=None):
            self.user_id = user_id or str(uuid.uuid4())
            self.is_running = False
            self.mock_stats = {
                "user_id": self.user_id,
                "is_running": False,
                "is_connected": False,
                "symbol": None,
                "strategy": "Average Last 5 Digits",
                "total_trades": 0,
                "successful_trades": 0,
                "win_rate": 0.0,
                "total_pnl": 0.0,
                "daily_pnl": 0.0,
                "current_balance": 1000.0,
                "current_target_digit": None,
                "trade_cycle_count": 0,
                "last_5_digits": [],
                "tick_analysis": {
                    "total_ticks_analyzed": 0,
                    "digit_frequencies": {str(i): 0 for i in range(10)},
                    "recent_ticks": [],
                    "last_5_calculation": {
                        "digits_collected": 0,
                        "digits": [],
                        "ready_to_trade": False,
                        "sum": 0,
                        "average": 0,
                        "target_digit": None
                    }
                },
                "uptime_minutes": 0,
                "connection_status": {
                    "connected": False,
                    "connection_attempts": 0,
                    "max_attempts": 3
                }
            }

        async def start(self, symbol, token, **kwargs):
            self.is_running = True
            self.mock_stats["is_running"] = True
            self.mock_stats["is_connected"] = True
            self.mock_stats["symbol"] = symbol
            return {"status": "started", "symbol": symbol, "strategy": "digit_differs_average", "user_id": self.user_id}

        async def stop(self):
            self.is_running = False
            self.mock_stats["is_running"] = False
            self.mock_stats["is_connected"] = False
            return {"status": "stopped", "user_id": self.user_id, "session_stats": self.mock_stats}

        def reset_data(self):
            self.mock_stats["total_trades"] = 0
            self.mock_stats["successful_trades"] = 0
            self.mock_stats["total_pnl"] = 0.0
            self.mock_stats["daily_pnl"] = 0.0
            self.mock_stats["current_target_digit"] = None
            self.mock_stats["trade_cycle_count"] = 0
            self.mock_stats["last_5_digits"] = []
            self.mock_stats["tick_analysis"]["total_ticks_analyzed"] = 0
            self.mock_stats["tick_analysis"]["digit_frequencies"] = {str(i): 0 for i in range(10)}
            self.mock_stats["tick_analysis"]["recent_ticks"] = []
            self.mock_stats["tick_analysis"]["last_5_calculation"] = {
                "digits_collected": 0,
                "digits": [],
                "ready_to_trade": False,
                "sum": 0,
                "average": 0,
                "target_digit": None
            }
            return {"status": "success", "message": "All tick data and statistics have been reset", "user_id": self.user_id}

        async def get_statistics(self):
            if self.is_running:
                # Simulate some activity
                self.mock_stats["total_trades"] = min(self.mock_stats["total_trades"] + 1, 50)
                self.mock_stats["tick_analysis"]["total_ticks_analyzed"] += 5
                self.mock_stats["uptime_minutes"] += 0.5
                # Simulate last 5 digits
                import random
                if len(self.mock_stats["last_5_digits"]) < 5:
                    self.mock_stats["last_5_digits"].append(random.randint(0, 9))
                else:
                    # Simulate calculation
                    digits = self.mock_stats["last_5_digits"]
                    digit_sum = sum(digits)
                    average = digit_sum / 5
                    target = int(average)
                    self.mock_stats["current_target_digit"] = target
                    self.mock_stats["tick_analysis"]["last_5_calculation"] = {
                        "digits_collected": 5,
                        "digits": digits.copy(),
                        "ready_to_trade": True,
                        "sum": digit_sum,
                        "average": average,
                        "target_digit": target
                    }
            return self.mock_stats

        async def force_trade(self):
            if not self.is_running:
                return {"status": "error", "message": "Bot not running"}
            
            target_digit = self.mock_stats.get("current_target_digit", 5)
            calculation = self.mock_stats["tick_analysis"]["last_5_calculation"]
            
            return {
                "status": "success", 
                "target_digit": target_digit, 
                "message": f"Force trade executed on digit {target_digit}",
                "calculation": calculation,
                "user_id": self.user_id
            }

        async def update_settings(self, **kwargs):
            return {"status": "settings_updated"}

    class MockDerivAPI:
        connected = False
        
        @staticmethod
        async def connect(token: str):
            MockDerivAPI.connected = True
            return {"message": "Mock connection successful"}

    # Mock user bot management
    mock_user_bots = {}
    
    def get_user_bot(user_id: str):
        if user_id not in mock_user_bots:
            mock_user_bots[user_id] = MockTradingBot(user_id)
        return mock_user_bots[user_id]
    
    def cleanup_inactive_bots():
        pass
    
    deriv_api = MockDerivAPI()

# FastAPI app
app = FastAPI(title="Enhanced Deriv Trading Bot API - Average Last 5 Digits")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request models
class BotStartRequest(BaseModel):
    symbol: Optional[str] = "R_100"
    token: str
    stake: Optional[float] = 1.0
    duration: Optional[int] = 5

class SettingsRequest(BaseModel):
    stake: Optional[float] = None
    trade_cooldown: Optional[int] = None
    daily_loss_limit: Optional[float] = None

# Utility functions
def generate_user_id(user_agent: str = None, ip: str = None, token: str = None) -> str:
    """Generate a consistent user ID based on browser/session info"""
    identifier_string = f"{user_agent or 'unknown'}:{ip or 'unknown'}:{token[:10] if token else 'notoken'}"
    return hashlib.md5(identifier_string.encode()).hexdigest()[:12]

def get_user_id_from_headers(user_agent: Optional[str] = None, x_forwarded_for: Optional[str] = None, x_user_session: Optional[str] = None) -> str:
    """Extract or generate user ID from request headers"""
    if x_user_session:
        return x_user_session[:12]
    return generate_user_id(user_agent, x_forwarded_for)

# Routes - Matching your frontend's expected endpoints
@app.get("/")
async def root():
    return {
        "message": "Average Last 5 Digits Trading Bot API", 
        "status": "running",
        "version": "2.1",
        "strategy": "Average Last 5 Digits → DIGITDIFF",
        "features": ["user_isolation", "reset_functionality", "real_time_monitoring"]
    }

# START BOT - Frontend expects POST /start
@app.post("/start")
async def start_bot(request: BotStartRequest, user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        # Get user-specific bot instance
        trading_bot = get_user_bot(user_id)
        
        result = await trading_bot.start(
            symbol=request.symbol,
            token=request.token,
            stake=request.stake or 1.0,
            duration=request.duration or 5
        )
        
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start bot: {str(e)}")

# STOP BOT - Frontend expects POST /stop
@app.post("/stop")
async def stop_bot(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        result = await trading_bot.stop()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to stop bot: {str(e)}")

# STATISTICS - Frontend expects GET /statistics
@app.get("/statistics")
async def get_statistics(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        return await trading_bot.get_statistics()
    except Exception as e:
        # Return default stats if bot not available
        return {
            "user_id": user_id,
            "is_running": False,
            "is_connected": False,
            "symbol": None,
            "strategy": "Average Last 5 Digits",
            "total_trades": 0,
            "successful_trades": 0,
            "win_rate": 0.0,
            "total_pnl": 0.0,
            "daily_pnl": 0.0,
            "current_balance": 0.0,
            "current_target_digit": None,
            "trade_cycle_count": 0,
            "last_5_digits": [],
            "tick_analysis": {
                "total_ticks_analyzed": 0,
                "digit_frequencies": {},
                "recent_ticks": [],
                "last_5_calculation": {
                    "digits_collected": 0,
                    "digits": [],
                    "ready_to_trade": False
                }
            },
            "uptime_minutes": 0,
            "connection_status": {
                "connected": False,
                "connection_attempts": 0,
                "max_attempts": 3
            },
            "error": str(e)
        }

# FORCE TRADE - Frontend expects POST /force-trade
@app.post("/force-trade")
async def execute_force_trade(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        return await trading_bot.force_trade()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute trade: {str(e)}")

# UPDATE SETTINGS - Frontend expects POST /update-settings
@app.post("/update-settings")
async def update_bot_settings(settings: SettingsRequest, user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        settings_dict = settings.dict(exclude_none=True)
        await trading_bot.update_settings(**settings_dict)
        return {
            "status": "settings_updated", 
            "updated": settings_dict, 
            "user_id": user_id
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update settings: {str(e)}")

# RESET DATA - Frontend expects POST /reset
@app.post("/reset")
async def reset_bot_data(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    try:
        trading_bot = get_user_bot(user_id)
        result = trading_bot.reset_data()
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to reset data: {str(e)}")

# Legacy API endpoints for backward compatibility
@app.get("/api/status")
async def legacy_get_status(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    """Legacy endpoint - redirects to statistics"""
    return await get_statistics(user_agent, x_forwarded_for, x_user_session)

@app.post("/api/start-bot")
async def legacy_start_bot(request: BotStartRequest, user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    """Legacy endpoint - redirects to start"""
    return await start_bot(request, user_agent, x_forwarded_for, x_user_session)

@app.post("/api/stop-bot")
async def legacy_stop_bot(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    """Legacy endpoint - redirects to stop"""
    return await stop_bot(user_agent, x_forwarded_for, x_user_session)

@app.get("/api/user-info")
async def get_user_info(user_agent: str = Header(None), x_forwarded_for: str = Header(None), x_user_session: str = Header(None)):
    user_id = get_user_id_from_headers(user_agent, x_forwarded_for, x_user_session)
    
    return {
        "user_id": user_id,
        "session_info": {
            "user_agent_hash": hashlib.md5((user_agent or "").encode()).hexdigest()[:8],
            "ip_hash": hashlib.md5((x_forwarded_for or "").encode()).hexdigest()[:8] if x_forwarded_for else None,
            "custom_session": x_user_session is not None
        }
    }

@app.post("/api/cleanup")
async def cleanup_inactive_sessions():
    try:
        cleanup_inactive_bots()
        return {"status": "success", "message": "Inactive sessions cleaned up"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cleanup failed: {str(e)}")

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "bot_available": True,
        "api_available": True,
        "strategy": "Average Last 5 Digits",
        "features": ["user_isolation", "reset_functionality", "real_time_monitoring"]
    }

if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting Average Last 5 Digits Trading Bot API...")
    print("🔒 Each user gets their own isolated bot instance")
    print("🔄 Reset functionality available for tick data")
    print("📊 Strategy: Average Last 5 Digits → DIGITDIFF contracts")
    print("🌐 Frontend: http://localhost:8000")
    print("📋 API Docs: http://localhost:8000/docs")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")