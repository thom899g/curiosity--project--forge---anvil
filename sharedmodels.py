"""
Data models for Forge event-driven architecture.
All models include validation and serialization for Firestore.
"""
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any, Union
from datetime import datetime
from enum import Enum
import uuid


class SignalAction(str, Enum):
    """Trading signal actions"""
    BUY = "BUY"
    SELL = "SELL"
    ARBITRAGE_BUY_SELL = "ARBITRAGE_BUY_SELL"  # Simultaneous buy/sell on different exchanges


class OrderStatus(str, Enum):
    """Order lifecycle status"""
    PENDING = "PENDING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class SweepState(str, Enum):
    """Treasury sweep state machine"""
    PROFIT_THRESHOLD_MET = "PROFIT_THRESHOLD_MET"
    AWAITING_MULTISIG_APPROVAL = "AWAITING_MULTISIG_APPROVAL"
    SWEEP_PENDING = "SWEEP_PENDING"
    SWEEP_COMPLETED = "SWEEP_COMPLETED"
    SWEEP_FAILED = "SWEEP_FAILED"


@dataclass
class MarketTick:
    """Normalized market tick from any source"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source: str  # e.g., 'binance', 'kraken', 'coinbase'
    pair: str  # e.g., 'USDC/USDT'
    price: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
    is_validated: bool = False
    validation_sources: List[str] = field(default_factory=list)
    volume_24h: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    
    def to_firestore(self) -> Dict[str, Any]:
        """Convert to Firestore-compatible dict"""
        data = asdict(self)
        data['timestamp'] = self.timestamp
        return data
    
    @classmethod
    def from_fire