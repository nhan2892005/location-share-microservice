-- Initialize database schema
CREATE DATABASE IF NOT EXISTS locationapp;

-- Create users table for auth service
CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL,
    first_name VARCHAR(50),
    last_name VARCHAR(50),
    phone_number VARCHAR(20),
    status VARCHAR(20) DEFAULT 'ACTIVE',
    roles TEXT[] DEFAULT '{"USER"}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    last_login TIMESTAMP
);

-- Create locations table for IoT service
CREATE TABLE IF NOT EXISTS locations (
    id BIGSERIAL PRIMARY KEY,
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
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for better performance
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_locations_user_id ON locations(user_id);
CREATE INDEX IF NOT EXISTS idx_locations_created_at ON locations(created_at);
CREATE INDEX IF NOT EXISTS idx_locations_coordinates ON locations(latitude, longitude);

-- Optional: Chat messages table for persistence (if needed)
CREATE TABLE IF NOT EXISTS chat_messages (
    id BIGSERIAL PRIMARY KEY,
    room_id VARCHAR(100) NOT NULL,
    sender_id BIGINT NOT NULL,
    message TEXT NOT NULL,
    message_type VARCHAR(20) DEFAULT 'text',
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_room_id ON chat_messages(room_id);
CREATE INDEX IF NOT EXISTS idx_chat_messages_created_at ON chat_messages(created_at);