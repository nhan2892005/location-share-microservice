package main

import (
    "context"
    "database/sql"
    "encoding/json"
    "fmt"
    "log"
    "net/http"
    "os"
    "strconv"
    "time"

    "github.com/gin-gonic/gin"
    "github.com/go-redis/redis/v8"
    "github.com/confluentinc/confluent-kafka-go/v2/kafka"
    "github.com/golang-jwt/jwt/v5"
    "github.com/gorilla/websocket"
    _ "github.com/lib/pq"
)

type Server struct {
    db       *sql.DB
    redis    *redis.Client
    producer *kafka.Producer
    consumer *kafka.Consumer
    upgrader websocket.Upgrader
}

type LocationData struct {
    UserID    int64   `json:"user_id"`
    Latitude  float64 `json:"latitude"`
    Longitude float64 `json:"longitude"`
    Altitude  float64 `json:"altitude,omitempty"`
    Accuracy  float64 `json:"accuracy,omitempty"`
    Speed     float64 `json:"speed,omitempty"`
    Heading   float64 `json:"heading,omitempty"`
    Timestamp int64   `json:"timestamp"`
}

type ProcessedLocation struct {
    LocationData
    Address     string `json:"address,omitempty"`
    City        string `json:"city,omitempty"`
    Country     string `json:"country,omitempty"`
    ProcessedAt int64  `json:"processed_at"`
}

type LocationRequest struct {
    Latitude  float64 `json:"latitude" binding:"required"`
    Longitude float64 `json:"longitude" binding:"required"`
    Altitude  float64 `json:"altitude,omitempty"`
    Accuracy  float64 `json:"accuracy,omitempty"`
    Speed     float64 `json:"speed,omitempty"`
    Heading   float64 `json:"heading,omitempty"`
}

type JWTClaims struct {
    UserID   int64  `json:"user_id"`
    Username string `json:"username"`
    jwt.RegisteredClaims
}

func main() {
    server := &Server{
        upgrader: websocket.Upgrader{
            CheckOrigin: func(r *http.Request) bool {
                return true // Allow all origins in dev
            },
        },
    }

    // Initialize dependencies
    if err := server.initDB(); err != nil {
        log.Fatal("Failed to initialize database:", err)
    }
    defer server.db.Close()

    if err := server.initRedis(); err != nil {
        log.Fatal("Failed to initialize Redis:", err)
    }
    defer server.redis.Close()

    if err := server.initKafka(); err != nil {
        log.Fatal("Failed to initialize Kafka:", err)
    }
    defer server.producer.Close()
    defer server.consumer.Close()

    // Start Kafka consumer in background
    go server.consumeLocationEvents()

    // Setup routes
    router := server.setupRoutes()

    port := getEnv("PORT", "8081")
    log.Printf("Go IoT Service starting on port %s", port)
    log.Fatal(http.ListenAndServe(":"+port, router))
}

func (s *Server) initDB() error {
    dbURL := getEnv("POSTGRES_URL", "postgres://appuser:apppass@localhost:5432/locationapp?sslmode=disable")
    var err error
    s.db, err = sql.Open("postgres", dbURL)
    if err != nil {
        return err
    }

    // Create locations table if not exists
    createTableQuery := `
    CREATE TABLE IF NOT EXISTS locations (
        id SERIAL PRIMARY KEY,
        user_id BIGINT NOT NULL,
        latitude DECIMAL(10, 8) NOT NULL,
        longitude DECIMAL(11, 8) NOT NULL,
        altitude DECIMAL(10, 2),
        accuracy DECIMAL(10, 2),
        speed DECIMAL(10, 2),
        heading DECIMAL(5, 2),
        address TEXT,
        city VARCHAR(100),
        country VARCHAR(100),
        created_at TIMESTAMP DEFAULT NOW(),
        INDEX idx_user_id (user_id),
        INDEX idx_created_at (created_at)
    );`
    
    _, err = s.db.Exec(createTableQuery)
    return err
}

func (s *Server) initRedis() error {
    redisURL := getEnv("REDIS_URL", "localhost:6379")
    s.redis = redis.NewClient(&redis.Options{
        Addr: redisURL,
    })

    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()
    
    _, err := s.redis.Ping(ctx).Result()
    return err
}

func (s *Server) initKafka() error {
    brokers := getEnv("KAFKA_BROKERS", "localhost:9092")

    // Producer
    producer, err := kafka.NewProducer(&kafka.ConfigMap{
        "bootstrap.servers": brokers,
        "client.id":         "go-iot-producer",
        "acks":             "all",
    })
    if err != nil {
        return err
    }
    s.producer = producer

    // Consumer
    consumer, err := kafka.NewConsumer(&kafka.ConfigMap{
        "bootstrap.servers": brokers,
        "group.id":         "go-iot-consumer",
        "auto.offset.reset": "earliest",
    })
    if err != nil {
        return err
    }
    s.consumer = consumer

    return nil
}

func (s *Server) setupRoutes() *gin.Engine {
    router := gin.Default()

    // Middleware
    router.Use(func(c *gin.Context) {
        c.Writer.Header().Set("Access-Control-Allow-Origin", "*")
        c.Writer.Header().Set("Access-Control-Allow-Credentials", "true")
        c.Writer.Header().Set("Access-Control-Allow-Headers", "Content-Type, Content-Length, Accept-Encoding, X-CSRF-Token, Authorization, accept, origin, Cache-Control, X-Requested-With")
        c.Writer.Header().Set("Access-Control-Allow-Methods", "POST, OPTIONS, GET, PUT, DELETE")

        if c.Request.Method == "OPTIONS" {
            c.AbortWithStatus(204)
            return
        }
        c.Next()
    })

    // Health check
    router.GET("/health", func(c *gin.Context) {
        c.JSON(200, gin.H{"status": "healthy", "service": "go-iot"})
    })

    // API routes
    api := router.Group("/api/iot")
    api.Use(s.authMiddleware())
    {
        api.POST("/location", s.handleLocationUpdate)
        api.GET("/location/:user_id", s.handleGetUserLocation)
        api.GET("/locations/nearby", s.handleGetNearbyLocations)
        api.GET("/locations/history", s.handleGetLocationHistory)
    }

    // WebSocket for real-time location updates
    router.GET("/ws/location", s.handleLocationWebSocket)

    return router
}

func (s *Server) authMiddleware() gin.HandlerFunc {
    return func(c *gin.Context) {
        authHeader := c.GetHeader("Authorization")
        if authHeader == "" {
            c.JSON(401, gin.H{"error": "Authorization header required"})
            c.Abort()
            return
        }

        tokenString := authHeader[7:] // Remove "Bearer " prefix
        if tokenString == "" {
            c.JSON(401, gin.H{"error": "Token required"})
            c.Abort()
            return
        }

        // Validate token (simple validation - in production, verify with auth service)
        token, err := jwt.ParseWithClaims(tokenString, &JWTClaims{}, func(token *jwt.Token) (interface{}, error) {
            return []byte(getEnv("JWT_SECRET", "your-super-secret-jwt-key-change-in-production")), nil
        })

        if err != nil || !token.Valid {
            c.JSON(401, gin.H{"error": "Invalid token"})
            c.Abort()
            return
        }

        claims := token.Claims.(*JWTClaims)
        c.Set("user_id", claims.UserID)
        c.Set("username", claims.Username)
        c.Next()
    }
}

func (s *Server) handleLocationUpdate(c *gin.Context) {
    var req LocationRequest
    if err := c.ShouldBindJSON(&req); err != nil {
        c.JSON(400, gin.H{"error": err.Error()})
        return
    }

    userID := c.GetInt64("user_id")
    
    locationData := LocationData{
        UserID:    userID,
        Latitude:  req.Latitude,
        Longitude: req.Longitude,
        Altitude:  req.Altitude,
        Accuracy:  req.Accuracy,
        Speed:     req.Speed,
        Heading:   req.Heading,
        Timestamp: time.Now().Unix(),
    }

    // Publish to Kafka for processing
    if err := s.publishLocationToKafka(locationData); err != nil {
        log.Printf("Failed to publish to Kafka: %v", err)
        c.JSON(500, gin.H{"error": "Failed to process location"})
        return
    }

    // Store current location in Redis for fast access
    if err := s.storeCurrentLocation(locationData); err != nil {
        log.Printf("Failed to store in Redis: %v", err)
    }

    c.JSON(200, gin.H{
        "success":   true,
        "message":   "Location updated successfully",
        "timestamp": locationData.Timestamp,
    })
}

func (s *Server) handleGetUserLocation(c *gin.Context) {
    userIDParam := c.Param("user_id")
    userID, err := strconv.ParseInt(userIDParam, 10, 64)
    if err != nil {
        c.JSON(400, gin.H{"error": "Invalid user ID"})
        return
    }

    // Get from Redis first (fastest)
    location, err := s.getCurrentLocation(userID)
    if err != nil {
        c.JSON(404, gin.H{"error": "Location not found"})
        return
    }

    c.JSON(200, location)
}

func (s *Server) handleGetNearbyLocations(c *gin.Context) {
    userID := c.GetInt64("user_id")
    
    // Get user's current location
    currentLocation, err := s.getCurrentLocation(userID)
    if err != nil {
        c.JSON(400, gin.H{"error": "Current location not found"})
        return
    }

    // Get radius parameter (default 1000 meters)
    radiusParam := c.DefaultQuery("radius", "1000")
    radius, _ := strconv.ParseFloat(radiusParam, 64)

    // Find nearby users from Redis
    nearbyUsers, err := s.findNearbyUsers(currentLocation.Latitude, currentLocation.Longitude, radius)
    if err != nil {
        c.JSON(500, gin.H{"error": "Failed to find nearby users"})
        return
    }

    c.JSON(200, gin.H{
        "nearby_users": nearbyUsers,
        "center":      currentLocation,
        "radius":      radius,
    })
}

func (s *Server) handleGetLocationHistory(c *gin.Context) {
    userID := c.GetInt64("user_id")
    
    limit := c.DefaultQuery("limit", "50")
    offset := c.DefaultQuery("offset", "0")
    
    query := `
        SELECT latitude, longitude, altitude, accuracy, speed, heading, 
               address, city, country, created_at 
        FROM locations 
        WHERE user_id = $1 
        ORDER BY created_at DESC 
        LIMIT $2 OFFSET $3`

    rows, err := s.db.Query(query, userID, limit, offset)
    if err != nil {
        c.JSON(500, gin.H{"error": "Failed to fetch location history"})
        return
    }
    defer rows.Close()

    var locations []ProcessedLocation
    for rows.Next() {
        var loc ProcessedLocation
        var createdAt time.Time
        
        err := rows.Scan(
            &loc.Latitude, &loc.Longitude, &loc.Altitude,
            &loc.Accuracy, &loc.Speed, &loc.Heading,
            &loc.Address, &loc.City, &loc.Country,
            &createdAt,
        )
        if err != nil {
            continue
        }
        
        loc.UserID = userID
        loc.ProcessedAt = createdAt.Unix()
        locations = append(locations, loc)
    }

    c.JSON(200, gin.H{"locations": locations})
}

func (s *Server) handleLocationWebSocket(c *gin.Context) {
    conn, err := s.upgrader.Upgrade(c.Writer, c.Request, nil)
    if err != nil {
        log.Printf("WebSocket upgrade failed: %v", err)
        return
    }
    defer conn.Close()

    // Subscribe to Redis channel for location updates
    pubsub := s.redis.Subscribe(context.Background(), "location_updates")
    defer pubsub.Close()

    for {
        msg, err := pubsub.ReceiveMessage(context.Background())
        if err != nil {
            log.Printf("Redis subscription error: %v", err)
            break
        }

        // Forward message to WebSocket client
        if err := conn.WriteMessage(websocket.TextMessage, []byte(msg.Payload)); err != nil {
            log.Printf("WebSocket write error: %v", err)
            break
        }
    }
}

func (s *Server) publishLocationToKafka(location LocationData) error {
    topic := "iot-locations"
    
    locationJSON, err := json.Marshal(location)
    if err != nil {
        return err
    }

    return s.producer.Produce(&kafka.Message{
        TopicPartition: kafka.TopicPartition{Topic: &topic, Partition: kafka.PartitionAny},
        Key:           []byte(strconv.FormatInt(location.UserID, 10)),
        Value:         locationJSON,
    }, nil)
}

func (s *Server) storeCurrentLocation(location LocationData) error {
    ctx := context.Background()
    key := fmt.Sprintf("location:current:%d", location.UserID)
    
    locationJSON, err := json.Marshal(location)
    if err != nil {
        return err
    }

    // Store current location with 1-hour expiration
    return s.redis.Set(ctx, key, locationJSON, time.Hour).Err()
}

func (s *Server) getCurrentLocation(userID int64) (*LocationData, error) {
    ctx := context.Background()
    key := fmt.Sprintf("location:current:%d", userID)
    
    result, err := s.redis.Get(ctx, key).Result()
    if err != nil {
        return nil, err
    }

    var location LocationData
    err = json.Unmarshal([]byte(result), &location)
    return &location, err
}

func (s *Server) findNearbyUsers(lat, lng, radius float64) ([]LocationData, error) {
    ctx := context.Background()
    pattern := "location:current:*"
    
    keys, err := s.redis.Keys(ctx, pattern).Result()
    if err != nil {
        return nil, err
    }

    var nearbyUsers []LocationData
    
    for _, key := range keys {
        result, err := s.redis.Get(ctx, key).Result()
        if err != nil {
            continue
        }

        var location LocationData
        if err := json.Unmarshal([]byte(result), &location); err != nil {
            continue
        }

        // Calculate distance (simplified Haversine)
        distance := calculateDistance(lat, lng, location.Latitude, location.Longitude)
        if distance <= radius {
            nearbyUsers = append(nearbyUsers, location)
        }
    }

    return nearbyUsers, nil
}

func (s *Server) consumeLocationEvents() {
    topics := []string{"iot-locations"}
    s.consumer.SubscribeTopics(topics, nil)

    for {
        msg, err := s.consumer.ReadMessage(-1)
        if err != nil {
            log.Printf("Kafka consumer error: %v", err)
            continue
        }

        var location LocationData
        if err := json.Unmarshal(msg.Value, &location); err != nil {
            log.Printf("Failed to unmarshal location data: %v", err)
            continue
        }

        // Process location (reverse geocoding, enrichment)
        processedLocation := s.processLocation(location)

        // Store in database
        if err := s.storeLocationInDB(processedLocation); err != nil {
            log.Printf("Failed to store location in DB: %v", err)
        }

        // Publish processed location
        if err := s.publishProcessedLocation(processedLocation); err != nil {
            log.Printf("Failed to publish processed location: %v", err)
        }

        // Publish to Redis for real-time updates
        if err := s.publishToRedisChannel(processedLocation); err != nil {
            log.Printf("Failed to publish to Redis channel: %v", err)
        }

        s.consumer.Commit()
    }
}

func (s *Server) processLocation(location LocationData) ProcessedLocation {
    processed := ProcessedLocation{
        LocationData: location,
        ProcessedAt:  time.Now().Unix(),
    }

    // Simple reverse geocoding (in production, use a proper service)
    processed.Address = fmt.Sprintf("%.6f, %.6f", location.Latitude, location.Longitude)
    processed.City = "Unknown"
    processed.Country = "Unknown"

    return processed
}

func (s *Server) storeLocationInDB(location ProcessedLocation) error {
    query := `
        INSERT INTO locations (user_id, latitude, longitude, altitude, accuracy, speed, heading, address, city, country)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)`

    _, err := s.db.Exec(query,
        location.UserID, location.Latitude, location.Longitude,
        location.Altitude, location.Accuracy, location.Speed, location.Heading,
        location.Address, location.City, location.Country)

    return err
}

func (s *Server) publishProcessedLocation(location ProcessedLocation) error {
    topic := "processed-iot"
    
    locationJSON, err := json.Marshal(location)
    if err != nil {
        return err
    }

    return s.producer.Produce(&kafka.Message{
        TopicPartition: kafka.TopicPartition{Topic: &topic, Partition: kafka.PartitionAny},
        Key:           []byte(strconv.FormatInt(location.UserID, 10)),
        Value:         locationJSON,
    }, nil)
}

func (s *Server) publishToRedisChannel(location ProcessedLocation) error {
    ctx := context.Background()
    locationJSON, err := json.Marshal(location)
    if err != nil {
        return err
    }

    return s.redis.Publish(ctx, "location_updates", locationJSON).Err()
}

// Utility functions
func getEnv(key, defaultValue string) string {
    if value := os.Getenv(key); value != "" {
        return value
    }
    return defaultValue
}

func calculateDistance(lat1, lng1, lat2, lng2 float64) float64 {
    // Simplified distance calculation (Euclidean distance)
    // In production, use proper Haversine formula
    dLat := lat2 - lat1
    dLng := lng2 - lng1
    return (dLat*dLat + dLng*dLng) * 111000 // Rough conversion to meters
}