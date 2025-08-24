#!/bin/bash
set -e

echo "🔄 Starting development environment..."

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker first."
    exit 1
fi

# Create Kafka topics
echo "📡 Creating Kafka topics..."
docker-compose up -d kafka zookeeper
sleep 10

docker-compose exec kafka kafka-topics --create --topic iot-locations --partitions 6 --replication-factor 1 --if-not-exists --bootstrap-server localhost:9092
docker-compose exec kafka kafka-topics --create --topic processed-iot --partitions 6 --replication-factor 1 --if-not-exists --bootstrap-server localhost:9092
docker-compose exec kafka kafka-topics --create --topic events.user.activity --partitions 3 --replication-factor 1 --if-not-exists --bootstrap-server localhost:9092
docker-compose exec kafka kafka-topics --create --topic chat.messages --partitions 6 --replication-factor 1 --if-not-exists --bootstrap-server localhost:9092
docker-compose exec kafka kafka-topics --create --topic media.events --partitions 3 --replication-factor 1 --if-not-exists --bootstrap-server localhost:9092

# Start all services
echo "🚀 Starting all services..."
docker-compose up -d

echo "✅ Development environment is ready!"
echo ""
echo "🌐 Service URLs:"
echo "  - API Gateway: http://localhost"
echo "  - Java Auth Service: http://localhost:8080"
echo "  - Go IoT Service: http://localhost:8081"
echo "  - Python Socket Service: http://localhost:8082"
echo "  - Kafka UI: http://localhost:8090"
echo "  - Redis Commander: http://localhost:8091"
echo ""
echo "📡 WebSocket Endpoints:"
echo "  - Chat: ws://localhost/ws/chat?token=YOUR_JWT"
echo "  - Location: ws://localhost/ws/location"
echo "  - WebRTC: ws://localhost/ws/webrtc/ROOM_ID?token=YOUR_JWT"
echo ""
echo "🔍 To view logs: docker-compose logs -f [service-name]"
echo "🛑 To stop: docker-compose down"