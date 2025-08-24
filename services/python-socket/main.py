import asyncio
import json
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

import jwt
import redis.asyncio as redis
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from kafka import KafkaProducer, KafkaConsumer
from pydantic import BaseModel
import uvicorn
import socketio

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Models
class ChatMessage(BaseModel):
    room_id: str
    sender_id: int
    message: str
    message_type: str = "text"  # text, image, file, etc.
    timestamp: Optional[int] = None

class WebRTCSignal(BaseModel):
    room_id: str
    sender_id: int
    signal_type: str  # offer, answer, ice-candidate
    signal_data: Dict[str, Any]
    target_user_id: Optional[int] = None

class CallEvent(BaseModel):
    room_id: str
    caller_id: int
    callee_ids: List[int]
    call_type: str  # audio, video
    action: str  # start, end, join, leave

class UserPresence(BaseModel):
    user_id: int
    status: str  # online, offline, busy, away
    last_seen: int

# Global variables
redis_client = None
kafka_producer = None
websocket_connections: Dict[int, WebSocket] = {}
room_participants: Dict[str, List[int]] = {}

# Configuration
JWT_SECRET = os.getenv("JWT_SECRET", "your-super-secret-jwt-key-change-in-production")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
KAFKA_BROKERS = os.getenv("KAFKA_BROKERS", "localhost:9092")
AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL", "http://localhost:8080")

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[int, WebSocket] = {}
        self.room_members: Dict[str, set] = {}
        
    async def connect(self, websocket: WebSocket, user_id: int):
        await websocket.accept()
        self.active_connections[user_id] = websocket
        logger.info(f"User {user_id} connected via WebSocket")
        
        # Update presence in Redis
        await self.update_user_presence(user_id, "online")

    async def disconnect(self, user_id: int):
        if user_id in self.active_connections:
            del self.active_connections[user_id]
        
        # Remove from all rooms
        for room_id, members in self.room_members.items():
            members.discard(user_id)
            if not members:
                del self.room_members[room_id]
        
        # Update presence in Redis
        await self.update_user_presence(user_id, "offline")
        logger.info(f"User {user_id} disconnected")

    async def join_room(self, room_id: str, user_id: int):
        if room_id not in self.room_members:
            self.room_members[room_id] = set()
        self.room_members[room_id].add(user_id)
        logger.info(f"User {user_id} joined room {room_id}")

    async def leave_room(self, room_id: str, user_id: int):
        if room_id in self.room_members:
            self.room_members[room_id].discard(user_id)
            if not self.room_members[room_id]:
                del self.room_members[room_id]
        logger.info(f"User {user_id} left room {room_id}")

    async def send_to_user(self, user_id: int, message: dict):
        if user_id in self.active_connections:
            try:
                await self.active_connections[user_id].send_json(message)
                return True
            except Exception as e:
                logger.error(f"Error sending message to user {user_id}: {e}")
                await self.disconnect(user_id)
        return False

    async def broadcast_to_room(self, room_id: str, message: dict, exclude_user_id: int = None):
        if room_id not in self.room_members:
            return

        disconnected_users = []
        for user_id in self.room_members[room_id]:
            if exclude_user_id and user_id == exclude_user_id:
                continue
                
            success = await self.send_to_user(user_id, message)
            if not success:
                disconnected_users.append(user_id)

        # Clean up disconnected users
        for user_id in disconnected_users:
            await self.disconnect(user_id)

    async def update_user_presence(self, user_id: int, status: str):
        try:
            presence = UserPresence(
                user_id=user_id,
                status=status,
                last_seen=int(time.time())
            )
            await redis_client.setex(
                f"presence:{user_id}",
                3600,  # 1 hour expiry
                json.dumps(presence.dict())
            )
            
            # Publish presence update
            await redis_client.publish(
                "presence_updates",
                json.dumps(presence.dict())
            )
        except Exception as e:
            logger.error(f"Failed to update presence for user {user_id}: {e}")

manager = ConnectionManager()

# Dependency for JWT validation
async def verify_token(authorization: str = Header(None)) -> int:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization header")
    
    token = authorization.split(" ")[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
        return user_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

# Lifespan events
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await startup_event()
    yield
    # Shutdown
    await shutdown_event()

# FastAPI app
app = FastAPI(title="Python Socket Service", lifespan=lifespan)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

async def startup_event():
    global redis_client, kafka_producer
    
    # Initialize Redis
    redis_client = redis.from_url(REDIS_URL)
    await redis_client.ping()
    logger.info("Connected to Redis")
    
    # Initialize Kafka producer
    kafka_producer = KafkaProducer(
        bootstrap_servers=KAFKA_BROKERS.split(","),
        value_serializer=lambda v: json.dumps(v).encode('utf-8'),
        key_serializer=lambda k: str(k).encode('utf-8') if k else None
    )
    logger.info("Connected to Kafka")
    
    # Start background tasks
    asyncio.create_task(consume_kafka_messages())

async def shutdown_event():
    global redis_client, kafka_producer
    
    if redis_client:
        await redis_client.close()
    
    if kafka_producer:
        kafka_producer.close()

# Health check
@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "python-socket"}

# WebSocket endpoint for chat
@app.websocket("/ws/chat")
async def websocket_chat_endpoint(websocket: WebSocket, token: str = None):
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except jwt.PyJWTError:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    await manager.connect(websocket, user_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            await handle_websocket_message(user_id, data)
    except WebSocketDisconnect:
        await manager.disconnect(user_id)
    except Exception as e:
        logger.error(f"WebSocket error for user {user_id}: {e}")
        await manager.disconnect(user_id)

async def handle_websocket_message(user_id: int, data: dict):
    message_type = data.get("type")
    
    if message_type == "join_room":
        room_id = data.get("room_id")
        if room_id:
            await manager.join_room(room_id, user_id)
            await manager.send_to_user(user_id, {
                "type": "room_joined",
                "room_id": room_id
            })
    
    elif message_type == "leave_room":
        room_id = data.get("room_id")
        if room_id:
            await manager.leave_room(room_id, user_id)
    
    elif message_type == "chat_message":
        await handle_chat_message(user_id, data)
    
    elif message_type == "webrtc_signal":
        await handle_webrtc_signal(user_id, data)
    
    elif message_type == "call_event":
        await handle_call_event(user_id, data)

async def handle_chat_message(sender_id: int, data: dict):
    try:
        message = ChatMessage(
            room_id=data["room_id"],
            sender_id=sender_id,
            message=data["message"],
            message_type=data.get("message_type", "text"),
            timestamp=int(time.time())
        )
        
        # Store in Redis for quick access
        await store_message_in_redis(message)
        
        # Publish to Kafka for persistence
        kafka_producer.send(
            "chat.messages",
            key=message.room_id,
            value=message.dict()
        )
        
        # Broadcast to room participants
        broadcast_message = {
            "type": "chat_message",
            "room_id": message.room_id,
            "sender_id": message.sender_id,
            "message": message.message,
            "message_type": message.message_type,
            "timestamp": message.timestamp
        }
        
        await manager.broadcast_to_room(message.room_id, broadcast_message, exclude_user_id=sender_id)
        
        # Publish to Redis pub/sub for scaling across instances
        await redis_client.publish(
            f"chat:{message.room_id}",
            json.dumps(broadcast_message)
        )
        
    except Exception as e:
        logger.error(f"Error handling chat message: {e}")

async def handle_webrtc_signal(sender_id: int, data: dict):
    try:
        signal = WebRTCSignal(
            room_id=data["room_id"],
            sender_id=sender_id,
            signal_type=data["signal_type"],
            signal_data=data["signal_data"],
            target_user_id=data.get("target_user_id")
        )
        
        broadcast_message = {
            "type": "webrtc_signal",
            "room_id": signal.room_id,
            "sender_id": signal.sender_id,
            "signal_type": signal.signal_type,
            "signal_data": signal.signal_data
        }
        
        if signal.target_user_id:
            # Send to specific user
            await manager.send_to_user(signal.target_user_id, broadcast_message)
        else:
            # Broadcast to room (excluding sender)
            await manager.broadcast_to_room(signal.room_id, broadcast_message, exclude_user_id=sender_id)
        
    except Exception as e:
        logger.error(f"Error handling WebRTC signal: {e}")

async def handle_call_event(sender_id: int, data: dict):
    try:
        call_event = CallEvent(
            room_id=data["room_id"],
            caller_id=sender_id,
            callee_ids=data.get("callee_ids", []),
            call_type=data.get("call_type", "audio"),
            action=data["action"]
        )
        
        # Publish to Kafka for analytics
        kafka_producer.send(
            "media.events",
            key=call_event.room_id,
            value=call_event.dict()
        )
        
        broadcast_message = {
            "type": "call_event",
            "room_id": call_event.room_id,
            "caller_id": call_event.caller_id,
            "call_type": call_event.call_type,
            "action": call_event.action
        }
        
        if call_event.action == "start":
            # Send call invitation to specific users
            for callee_id in call_event.callee_ids:
                await manager.send_to_user(callee_id, broadcast_message)
        else:
            # Broadcast to room participants
            await manager.broadcast_to_room(call_event.room_id, broadcast_message, exclude_user_id=sender_id)
        
    except Exception as e:
        logger.error(f"Error handling call event: {e}")

async def store_message_in_redis(message: ChatMessage):
    try:
        # Store recent messages for quick retrieval
        key = f"messages:{message.room_id}"
        await redis_client.lpush(key, json.dumps(message.dict()))
        await redis_client.ltrim(key, 0, 99)  # Keep last 100 messages
        await redis_client.expire(key, 86400)  # 24 hours expiry
    except Exception as e:
        logger.error(f"Error storing message in Redis: {e}")

# REST API endpoints
@app.get("/api/chat/rooms/{room_id}/messages")
async def get_room_messages(room_id: str, limit: int = 50, user_id: int = Depends(verify_token)):
    try:
        # Get from Redis first
        messages = await redis_client.lrange(f"messages:{room_id}", 0, limit - 1)
        result = []
        
        for msg in messages:
            try:
                result.append(json.loads(msg))
            except json.JSONDecodeError:
                continue
        
        return {"messages": result[::-1]}  # Reverse to get chronological order
    except Exception as e:
        logger.error(f"Error fetching messages: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch messages")

@app.get("/api/chat/rooms/{room_id}/participants")
async def get_room_participants(room_id: str, user_id: int = Depends(verify_token)):
    try:
        participants = []
        if room_id in manager.room_members:
            for participant_id in manager.room_members[room_id]:
                # Get user presence
                presence_data = await redis_client.get(f"presence:{participant_id}")
                if presence_data:
                    presence = json.loads(presence_data)
                    participants.append({
                        "user_id": participant_id,
                        "status": presence.get("status", "offline"),
                        "last_seen": presence.get("last_seen")
                    })
        
        return {"participants": participants}
    except Exception as e:
        logger.error(f"Error fetching room participants: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch participants")

@app.post("/api/chat/rooms/{room_id}/join")
async def join_room_http(room_id: str, user_id: int = Depends(verify_token)):
    try:
        await manager.join_room(room_id, user_id)
        return {"success": True, "message": f"Joined room {room_id}"}
    except Exception as e:
        logger.error(f"Error joining room: {e}")
        raise HTTPException(status_code=500, detail="Failed to join room")

@app.post("/api/chat/rooms/{room_id}/leave")
async def leave_room_http(room_id: str, user_id: int = Depends(verify_token)):
    try:
        await manager.leave_room(room_id, user_id)
        return {"success": True, "message": f"Left room {room_id}"}
    except Exception as e:
        logger.error(f"Error leaving room: {e}")
        raise HTTPException(status_code=500, detail="Failed to leave room")

@app.get("/api/presence/users/{target_user_id}")
async def get_user_presence(target_user_id: int, user_id: int = Depends(verify_token)):
    try:
        presence_data = await redis_client.get(f"presence:{target_user_id}")
        if presence_data:
            presence = json.loads(presence_data)
            return presence
        else:
            return {"user_id": target_user_id, "status": "offline", "last_seen": None}
    except Exception as e:
        logger.error(f"Error fetching user presence: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch presence")

@app.post("/api/presence/update")
async def update_presence(status: str, user_id: int = Depends(verify_token)):
    try:
        await manager.update_user_presence(user_id, status)
        return {"success": True, "status": status}
    except Exception as e:
        logger.error(f"Error updating presence: {e}")
        raise HTTPException(status_code=500, detail="Failed to update presence")

# Background task to consume Kafka messages
async def consume_kafka_messages():
    loop = asyncio.get_event_loop()
    
    def kafka_consumer_task():
        consumer = KafkaConsumer(
            'processed-iot',
            'events.user.activity',
            bootstrap_servers=KAFKA_BROKERS.split(","),
            group_id='python-socket-consumer',
            value_deserializer=lambda m: json.loads(m.decode('utf-8')),
            auto_offset_reset='latest'
        )
        
        for message in consumer:
            # Schedule coroutine on the event loop
            asyncio.run_coroutine_threadsafe(
                process_kafka_message(message.topic, message.value),
                loop
            )
    
    # Run Kafka consumer in thread to avoid blocking
    import threading
    kafka_thread = threading.Thread(target=kafka_consumer_task, daemon=True)
    kafka_thread.start()

async def process_kafka_message(topic: str, message: dict):
    try:
        if topic == 'processed-iot':
            # Handle location updates
            await handle_location_update(message)
        elif topic == 'events.user.activity':
            # Handle user activity events
            await handle_user_activity(message)
    except Exception as e:
        logger.error(f"Error processing Kafka message from {topic}: {e}")

async def handle_location_update(location_data: dict):
    try:
        # Broadcast location update to interested parties
        user_id = location_data.get('user_id')
        if user_id:
            # Find users who should receive this location update
            # (friends, family, etc. - implement your logic here)
            
            broadcast_message = {
                "type": "location_update",
                "user_id": user_id,
                "latitude": location_data.get('latitude'),
                "longitude": location_data.get('longitude'),
                "timestamp": location_data.get('processed_at')
            }
            
            # For demo, broadcast to all connected users
            # In production, implement proper privacy controls
            for connected_user_id in manager.active_connections.keys():
                if connected_user_id != user_id:
                    await manager.send_to_user(connected_user_id, broadcast_message)
                    
    except Exception as e:
        logger.error(f"Error handling location update: {e}")

async def handle_user_activity(activity_data: dict):
    try:
        # Handle user login/logout events
        user_id = activity_data.get('user_id')
        activity_type = activity_data.get('activity_type')
        
        if activity_type in ['login', 'logout']:
            status = 'online' if activity_type == 'login' else 'offline'
            await manager.update_user_presence(user_id, status)
            
    except Exception as e:
        logger.error(f"Error handling user activity: {e}")

# WebSocket endpoint for WebRTC signaling
@app.websocket("/ws/webrtc/{room_id}")
async def websocket_webrtc_endpoint(websocket: WebSocket, room_id: str, token: str = None):
    if not token:
        await websocket.close(code=4001, reason="Token required")
        return
    
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = int(payload.get("sub"))
    except jwt.PyJWTError:
        await websocket.close(code=4001, reason="Invalid token")
        return
    
    await websocket.accept()
    await manager.join_room(f"webrtc:{room_id}", user_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            
            # Handle WebRTC signaling messages
            if data.get("type") in ["offer", "answer", "ice-candidate", "join-room", "leave-room"]:
                # Broadcast to other participants in the room
                broadcast_data = {
                    **data,
                    "sender_id": user_id,
                    "timestamp": int(time.time())
                }
                
                await manager.broadcast_to_room(
                    f"webrtc:{room_id}", 
                    broadcast_data, 
                    exclude_user_id=user_id
                )
                
    except WebSocketDisconnect:
        await manager.leave_room(f"webrtc:{room_id}", user_id)
    except Exception as e:
        logger.error(f"WebRTC WebSocket error for user {user_id}: {e}")
        await manager.leave_room(f"webrtc:{room_id}", user_id)

# Utility functions for TURN server integration (optional)
@app.get("/api/webrtc/ice-servers")
async def get_ice_servers(user_id: int = Depends(verify_token)):
    # Return STUN/TURN server configuration
    # In production, generate temporary credentials for TURN
    return {
        "iceServers": [
            {"urls": "stun:stun.l.google.com:19302"},
            # Add TURN server configuration here
            # {
            #     "urls": "turn:your-turn-server.com:3478",
            #     "username": "generated_username",
            #     "credential": "generated_password"
            # }
        ]
    }

# Monitoring and metrics endpoints
@app.get("/api/stats/connections")
async def get_connection_stats():
    return {
        "active_connections": len(manager.active_connections),
        "active_rooms": len(manager.room_members),
        "total_room_participants": sum(len(members) for members in manager.room_members.values())
    }

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8082,
        log_level="info",
        reload=False  # Set to True for development
    )