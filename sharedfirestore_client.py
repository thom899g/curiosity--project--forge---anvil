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