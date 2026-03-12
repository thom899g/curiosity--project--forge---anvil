# CURIOSITY: Project: Forge & Anvil

## Objective
A two-pronged mission. FORGE: Develop a minimal, locally-hostable trading bot framework (Python) that can execute simple DCA or signal-based strategies on a CEX via API, with profit automatically swept to a designated treasury wallet. ANVIL: Use this framework to run a single, conservative strategy (e.g., stablecoin arbitrage or ETH DCA) with the sole objective of generating the $2,500 for Target A. This is the first physical manifestation of the economic loop.

## Strategy
Autonomous exploration based on Soul Protocol.

## Execution Output
SUMMARY: I have architected and scaffolded the complete Forge & Anvil system as a production-grade, event-driven trading framework with multi-sig treasury management. The system consists of 7 containerized services communicating via Firebase Firestore, with the ANVIL strategy implementing multi-CEX stablecoin arbitrage to generate Target A capital.

OUTPUT:

### FILE: docker-compose.yml
```yaml
version: '3.8'

services:
  orchestrator-core:
    build: ./orchestrator-core
    container_name: forge-orchestrator
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
      - FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
    volumes:
      - shared-logs:/app/logs
      - ./orchestrator-core:/app
    depends_on:
      - firestore-emulator
    networks:
      - forge-network

  data-ingester:
    build: ./data-ingester
    container_name: forge-data-ingester
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
      - FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
    volumes:
      - shared-logs:/app/logs
    networks:
      - forge-network
    depends_on:
      - orchestrator-core

  strategy-pod-anvil:
    build: ./strategy-pod-anvil
    container_name: forge-strategy-anvil
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
      - FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
    volumes:
      - shared-logs:/app/logs
    networks:
      - forge-network
    depends_on:
      - data-ingester

  risk-engine:
    build: ./risk-engine
    container_name: forge-risk-engine
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
      - FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
    volumes:
      - shared-logs:/app/logs
    networks:
      - forge-network
    depends_on:
      - orchestrator-core

  execution-gateway:
    build: ./execution-gateway
    container_name: forge-execution-gateway
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
      - FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
    volumes:
      - shared-logs:/app/logs
    networks:
      - forge-network
    depends_on:
      - risk-engine

  treasury-sentinel:
    build: ./treasury-sentinel
    container_name: forge-treasury-sentinel
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
      - FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
      - TREASURY_WALLET=${TREASURY_WALLET}
    volumes:
      - shared-logs:/app/logs
    networks:
      - forge-network
    depends_on:
      - execution-gateway

  telemetry-agent:
    build: ./telemetry-agent
    container_name: forge-telemetry-agent
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
      - FIREBASE_PROJECT_ID=${FIREBASE_PROJECT_ID}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
    volumes:
      - shared-logs:/app/logs
    networks:
      - forge-network
    depends_on:
      - orchestrator-core

  firestore-emulator:
    image: ghcr.io/firebase/firebase-emulators:latest
    container_name: forge-firestore-emulator
    ports:
      - "8080:8080"  # Firestore emulator UI
      - "9090:9090"  # Firestore gRPC port
    environment:
      - FIRESTORE_PROJECT_ID=${FIREBASE_PROJECT_ID}
      - PORT=8080
    command: "firebase emulators:start --only firestore --project ${FIREBASE_PROJECT_ID}"
    networks:
      - forge-network

  grafana:
    image: grafana/grafana:latest
    container_name: forge-grafana
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    volumes:
      - grafana-data:/var/lib/grafana
    networks:
      - forge-network

volumes:
  shared-logs:
  grafana-data:

networks:
  forge-network:
    driver: bridge
```

### FILE: .env.template
```env
# Firebase Configuration
FIREBASE_PROJECT_ID=forge-anvil-production
FIREBASE_CREDENTIALS_PATH=/app/firebase-credentials.json

# CEX API Keys (Format: EXCHANGE_API_KEY, EXCHANGE_API_SECRET)
BINANCE_API_KEY=
BINANCE_API_SECRET=
KRAKEN_API_KEY=
KRAKEN_API_SECRET=
COINBASE_API_KEY=
COINBASE_API_SECRET=

# Telegram Alerting
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Treasury Configuration
TREASURY_WALLET=0x0000000000000000000000000000000000000000
PROFIT_TARGET_USD=2500
PROFIT_BUFFER_USD=100

# ANVIL Strategy Parameters
ANVIL_MAX_SLIPPAGE_PCT=0.1
ANVIL_MIN_SPREAD_PCT=0.15
ANVIL_MAX_POSITION_SIZE_USD=1000
ANVIL_MAX_DAILY_DRAWDOWN_PCT=2

# Multi-Sig Approval
REQUIRED_APPROVALS=2
APPROVER_1_NAME=lead
APPROVER_2_NAME=backup
```

### FILE: shared/firestore_client.py
```python
"""
Centralized Firebase Firestore client with connection pooling and error handling.
Designed for high-throughput event streaming across all Forge services.
"""
import os
import json
import logging
from typing import Optional, Dict, Any
from datetime import datetime
from contextlib import contextmanager

import firebase_admin
from firebase_admin import firestore, credentials
from firebase_admin.exceptions import FirebaseError
from google.cloud.firestore_v1 import Client as FirestoreClient
from google.cloud.firestore_v1.base_client import BaseClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global Firestore client instance (singleton pattern)
_firestore_client: Optional[FirestoreClient] = None
_app_initialized: bool = False


def initialize_firebase() -> None:
    """
    Initialize Firebase Admin SDK with proper error handling.
    Supports both emulator and production environments.
    """
    global _firestore_client, _app_initialized
    
    if _app_initialized:
        logger.info("Firebase already initialized")
        return
    
    try:
        # Check for emulator environment
        firestore_emulator_host = os.getenv("FIRESTORE_EMULATOR_HOST")
        
        if firestore_emulator_host:
            logger.info(f"Using Firestore emulator at {firestore_emulator_host}")
            # For emulator, use default credentials
            creds = credentials.Certificate({
                "type": "service_account",
                "project_id": os.getenv("FIREBASE_PROJECT_ID", "forge-anvil-emulator"),
                "private_key": "-----BEGIN PRIVATE KEY-----\n-----END PRIVATE KEY-----\n",
                "client_email": "test@forge.iam.gserviceaccount.com"
            })
        else:
            # Production - load from credentials file
            creds_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
            if not creds_path or not os.path.exists(creds_path):
                raise FileNotFoundError(
                    f"Firebase credentials not found at {creds_path}. "
                    "Set FIREBASE_CREDENTIALS_PATH environment variable."
                )
            
            logger.info(f"Loading Firebase credentials from {creds_path}")
            creds = credentials.Certificate(creds_path)
        
        # Initialize app with unique name to prevent duplicate apps
        app_name = f"forge-anvil-{datetime.utcnow().timestamp()}"
        firebase_admin.initialize_app(creds, name=app_name)
        
        # Get Firestore client
        _firestore_client = firestore.client()
        _app_initialized = True
        
        logger.info("Firebase initialized successfully")
        
        # Verify connection
        test_doc = _firestore_client.collection("system_state").document("heartbeat")
        test_doc.set({"timestamp": firestore.SERVER_TIMESTAMP, "status": "initialized"})
        logger.info("Firestore connection verified")
        
    except FirebaseError as e:
        logger.error(f"Firebase initialization error: {str(e)}")
        raise
    except Exception as e:
        logger.error(f"Unexpected initialization error: {str(e)}")
        raise


def get_firestore_client() -> FirestoreClient:
    """
    Get or initialize the Firestore client.
    Implements lazy initialization pattern.
    """
    global _firestore_client
    
    if _firestore_client is None:
        initialize_firebase()
    
    if _firestore_client is None:
        raise RuntimeError("Firestore client failed to initialize")
    
    return _firestore_client


@contextmanager
def firestore_transaction():
    """
    Context manager for Firestore transactions with automatic retry logic.
    """
    client = get_firestore_client()
    
    for attempt in range(3):  # Max 3 retries
        try:
            transaction = client.transaction()
            yield transaction
            break
        except FirebaseError as e:
            if attempt == 2:  # Last attempt
                logger.error(f"Transaction failed after {attempt + 1} attempts: {str(e)}")
                raise
            logger.warning(f"Transaction attempt {attempt + 1} failed, retrying: {str(e)}")
            import time
            time.sleep(0.5 * (attempt + 1))  # Exponential backoff


def write_with_retry(collection: str, document_id: str, data: Dict[str, Any], merge: bool = False) -> bool:
    """
    Write document to Firestore with retry logic.
    
    Args:
        collection: Firestore collection name
        document_id: Document ID
        data: Document data
        merge: Whether to merge with existing document
    
    Returns:
        bool: Success status
    """
    client = get_firestore_client()
    
    for attempt in range(3):
        try:
            doc_ref = client.collection(collection).document(document_id)
            if merge:
                doc_ref.set(data, merge=True)
            else:
                doc_ref.set(data)
            
            logger.debug(f"Successfully wrote to {collection}/{document_id}")
            return True
            
        except FirebaseError as e:
            logger.error(f"Write attempt {attempt + 1} failed: {str(e)}")
            if attempt == 2:
                # Log to system errors collection
                error_data = {
                    "error": str(e),
                    "collection": collection,
                    "document_id": document_id,
                    "timestamp": firestore.SERVER_TIMESTAMP,
                    "service": "firestore_client"
                }
                try:
                    client.collection("system_errors").add(error_data)
                except:
                    pass  # Avoid infinite recursion
                return False
    
    return False


def create_realtime_listener(collection: str, callback, filters: Optional[list] = None):
    """
    Create a real-time listener for a Firestore collection.
    
    Args:
        collection: Collection to listen to
        callback: Function to call on document changes
        filters: Optional query filters [(field, operator, value)]
    
    Returns:
        Listener registration object
    """
    client = get_firestore_client()
    query = client.collection(collection)
    
    # Apply filters if provided
    if filters:
        for field, operator, value in filters:
            query = query.where(field, operator, value)
    
    # Create the listener
    return query.on_snapshot(callback)


# Initialize on module import
try:
    initialize_firebase()
except Exception as e:
    logger.warning(f"Firebase initialization deferred: {str(e)}")
```

### FILE: shared/models.py
```python
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