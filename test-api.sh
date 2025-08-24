#!/bin/bash
set -e

BASE_URL="http://localhost"

echo "🧪 Testing Location Sharing Microservices API..."

# Test health endpoints
echo "1. Testing health checks..."
curl -f "$BASE_URL/health" || echo "❌ API Gateway health failed"
curl -f "$BASE_URL/api/auth/health" || echo "❌ Auth service health failed"
curl -f "$BASE_URL/api/iot/health" || echo "❌ IoT service health failed"
curl -f "$BASE_URL/api/chat/health" || echo "❌ Socket service health failed"

# Test user registration
echo "2. Testing user registration..."
REGISTER_RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/register" \
    -H "Content-Type: application/json" \
    -d '{
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123",
        "firstName": "Test",
        "lastName": "User"
    }')

echo "Register response: $REGISTER_RESPONSE"

# Extract JWT token
TOKEN=$(echo $REGISTER_RESPONSE | grep -o '"accessToken":"[^"]*' | cut -d'"' -f4)

if [ -z "$TOKEN" ]; then
    echo "❌ Registration failed or token not found"
    exit 1
fi

echo "✅ Got token: ${TOKEN:0:20}..."

# Test location update
echo "3. Testing location update..."
curl -s -X POST "$BASE_URL/api/iot/location" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d '{
        "latitude": 10.762622,
        "longitude": 106.660172,
        "accuracy": 10
    }'

# Test location retrieval
echo "4. Testing location retrieval..."
curl -s "$BASE_URL/api/iot/locations/nearby?radius=1000" \
    -H "Authorization: Bearer $TOKEN"

echo ""
echo "✅ Basic API tests completed!"
echo "🔗 WebSocket tests require a WebSocket client"